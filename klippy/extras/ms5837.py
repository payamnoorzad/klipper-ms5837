# Klipper MS5837 pressure sensor support
# Supports MS5837-02BA and MS5837-30BA.
#
# G-code commands:
#   MS_PRESSURE_QUERY [SENSOR=<name>] [SAMPLES=<count>]
#   MS_PRESSURE_ZERO [SENSOR=<name>] [SAMPLES=<count>]
#   MS_PRESSURE_STATUS [SENSOR=<name>]
#
# Status fields are exported for printer.objects.query.

from . import bus
import math


class MS5837Sensor:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split(None, 1)[1] if " " in config.get_name() else "default"

        self.model = config.getchoice(
            "model",
            {"02BA": "02BA", "30BA": "30BA"},
            default="02BA"
        )

        self.pressure_unit = config.getchoice(
            "pressure_unit",
            {
                "mbar": "mbar",
                "bar": "bar",
                "kpa": "kPa",
                "pa": "Pa",
                "psi": "psi",
            },
            default="mbar"
        )

        self.sample_interval = config.getfloat(
            "sample_interval", 0.5, minval=0.05
        )
        self.filter_samples = config.getint(
            "filter_samples", 5, minval=1, maxval=100
        )
        self.fluid_density = config.getfloat(
            "fluid_density", 997.0, above=0.0
        )
        self.auto_start = config.getboolean("auto_start", False)

        self.i2c = bus.MCU_I2C_from_config(
            config,
            default_addr=0x76,
            default_speed=100000
        )

        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")

        self.prom = [0] * 7
        self.initialized = False
        self.crc_ok = False
        self.zero_pressure_mbar = None
        self.last_pressure_mbar = None
        self.last_temperature_c = None
        self.last_gauge_mbar = None
        self.last_depth_m = None
        self.last_d1 = None
        self.last_d2 = None
        self.last_error = None
        self.samples = []

        # Prevent overlapping / duplicate sensor transactions.
        # Background sampling owns normal I2C reads; G-code query/status
        # commands should normally use the latest cached sample or burst read.
        self.reading = False

        self.gcode.register_mux_command(
            "MS_PRESSURE_QUERY", "SENSOR", self.name,
            self.cmd_MS_PRESSURE_QUERY,
            desc="Read MS5837 pressure and temperature"
        )
        self.gcode.register_mux_command(
            "MS_PRESSURE_ZERO", "SENSOR", self.name,
            self.cmd_MS_PRESSURE_ZERO,
            desc="Set current MS5837 pressure as zero reference"
        )
        self.gcode.register_mux_command(
            "MS_PRESSURE_STATUS", "SENSOR", self.name,
            self.cmd_MS_PRESSURE_STATUS,
            desc="Show MS5837 status and calibration information"
        )

        self.printer.register_event_handler(
            "klippy:ready", self._handle_ready
        )

        self.sample_timer = self.reactor.register_timer(
            self._sample_timer
        )

    # ---------- Low-level sensor operations ----------

    def _reset_sensor(self):
        self.i2c.i2c_write([0x1E])
        self.reactor.pause(self.reactor.monotonic() + 0.010)

    def _read_prom(self):
        prom = []
        for i in range(7):
            command = 0xA0 + (i * 2)
            result = self.i2c.i2c_read([command], 2)
            data = result["response"]
            value = (data[0] << 8) | data[1]
            prom.append(value)

        self.prom = prom
        self.crc_ok = self._crc4_ok(prom)

    def _crc4_ok(self, prom7):
        # Datasheet-style CRC4 check.
        #
        # We currently read PROM words 0..6. The 4-bit CRC nibble is stored
        # in the upper nibble of C0 for MS5837. This implementation verifies
        # against the same algorithm used by common MS5837 drivers.
        #
        # Build an 8-word buffer, with the last word treated as zero.
        n_prom = list(prom7) + [0]
        crc_read = (n_prom[0] >> 12) & 0xF
        n_prom[0] &= 0x0FFF
        n_rem = 0

        for cnt in range(16):
            if cnt % 2 == 1:
                n_rem ^= n_prom[cnt >> 1] & 0x00FF
            else:
                n_rem ^= n_prom[cnt >> 1] >> 8

            for _ in range(8):
                if n_rem & 0x8000:
                    n_rem = ((n_rem << 1) ^ 0x3000) & 0xFFFF
                else:
                    n_rem = (n_rem << 1) & 0xFFFF

        crc_calc = (n_rem >> 12) & 0xF
        return crc_calc == crc_read

    def _read_adc(self, command):
        self.i2c.i2c_write([command])
        # OSR=8192 conversion time: allow margin (nominal 14.1ms, max 17.0ms).
        self.reactor.pause(self.reactor.monotonic() + 0.020)
        result = self.i2c.i2c_read([0x00], 3)
        data = result["response"]
        return (data[0] << 16) | (data[1] << 8) | data[2]

    def _initialize(self):
        self._reset_sensor()
        self._read_prom()

        # All-zero / all-ones PROM usually indicates a bad read.
        if all(v == 0x0000 for v in self.prom):
            raise self.printer.command_error(
                "MS5837 PROM read returned all zeros"
            )
        if all(v == 0xFFFF for v in self.prom):
            raise self.printer.command_error(
                "MS5837 PROM read returned all 0xFFFF"
            )

        self.initialized = True
        self.last_error = None

    # ---------- Compensation ----------

    def _read_02ba(self):
        c1 = self.prom[1]
        c2 = self.prom[2]
        c3 = self.prom[3]
        c4 = self.prom[4]
        c5 = self.prom[5]
        c6 = self.prom[6]

        d1 = self._read_adc(0x4A)  # D1, OSR=8192
        d2 = self._read_adc(0x5A)  # D2, OSR=8192

        dT = d2 - (c5 * 256)

        temp = 2000.0 + ((dT * c6) / 8388608.0)
        off = (c2 * 131072.0) + ((c4 * dT) / 64.0)
        sens = (c1 * 65536.0) + ((c3 * dT) / 128.0)

        # Second-order compensation for MS5837-02BA.
        if temp < 2000.0:
            ti = (11.0 * dT * dT) / 34359738368.0
            offi = (31.0 * (temp - 2000.0) ** 2) / 8.0
            sensi = (63.0 * (temp - 2000.0) ** 2) / 32.0
        else:
            ti = 0.0
            offi = 0.0
            sensi = 0.0

        temp2 = temp - ti
        off2 = off - offi
        sens2 = sens - sensi

        pressure_raw = (((d1 * sens2) / 2097152.0) - off2) / 32768.0
        pressure_mbar = pressure_raw / 100.0
        temperature_c = temp2 / 100.0

        return pressure_mbar, temperature_c, d1, d2

    def _read_30ba(self):
        c1 = self.prom[1]
        c2 = self.prom[2]
        c3 = self.prom[3]
        c4 = self.prom[4]
        c5 = self.prom[5]
        c6 = self.prom[6]

        d1 = self._read_adc(0x4A)  # D1, OSR=8192
        d2 = self._read_adc(0x5A)  # D2, OSR=8192

        dT = d2 - (c5 * 256)

        temp = 2000.0 + ((dT * c6) / 8388608.0)
        off = (c2 * 65536.0) + ((c4 * dT) / 128.0)
        sens = (c1 * 32768.0) + ((c3 * dT) / 256.0)

        # Second-order compensation for MS5837-30BA.
        if temp < 2000.0:
            ti = (3.0 * dT * dT) / 8589934592.0
            offi = (3.0 * (temp - 2000.0) ** 2) / 2.0
            sensi = (5.0 * (temp - 2000.0) ** 2) / 8.0
            if temp < -1500.0:
                offi += 7.0 * (temp + 1500.0) ** 2
                sensi += 4.0 * (temp + 1500.0) ** 2
        else:
            ti = (2.0 * dT * dT) / 137438953472.0
            offi = ((temp - 2000.0) ** 2) / 16.0
            sensi = 0.0

        temp2 = temp - ti
        off2 = off - offi
        sens2 = sens - sensi

        pressure_raw = (((d1 * sens2) / 2097152.0) - off2) / 8192.0
        pressure_mbar = pressure_raw / 10.0
        temperature_c = temp2 / 100.0

        return pressure_mbar, temperature_c, d1, d2

    def _read_once(self):
        if not self.initialized:
            self._initialize()

        if self.model == "02BA":
            pressure_mbar, temperature_c, d1, d2 = self._read_02ba()
        else:
            pressure_mbar, temperature_c, d1, d2 = self._read_30ba()

        return {
            "pressure_mbar": pressure_mbar,
            "temperature_c": temperature_c,
            "d1": d1,
            "d2": d2,
        }

    # ---------- Filtering / derived values ----------

    def _apply_filter(self, pressure_mbar):
        self.samples.append(pressure_mbar)
        if len(self.samples) > self.filter_samples:
            self.samples = self.samples[-self.filter_samples:]
        return sum(self.samples) / len(self.samples)

    def _read_burst_samples(self, count=1):
        if self.reading:
            raise self.printer.command_error(
                "MS5837 sensor read is already in progress"
            )

        self.reading = True
        try:
            pressures = []
            temps = []
            last_d1 = None
            last_d2 = None

            for _ in range(count):
                data = self._read_once()
                pressures.append(data["pressure_mbar"])
                temps.append(data["temperature_c"])
                last_d1 = data["d1"]
                last_d2 = data["d2"]

            avg_pressure = sum(pressures) / len(pressures)
            avg_temp = sum(temps) / len(temps)

            # Sync rolling buffer with the fresh readings
            self.samples = pressures[-self.filter_samples:]

            gauge = None
            if self.zero_pressure_mbar is not None:
                gauge = avg_pressure - self.zero_pressure_mbar

            depth = None
            if gauge is not None:
                # 1 mbar = 100 Pa
                depth = (gauge * 100.0) / (self.fluid_density * 9.80665)

            self.last_pressure_mbar = avg_pressure
            self.last_temperature_c = avg_temp
            self.last_gauge_mbar = gauge
            self.last_depth_m = depth
            self.last_d1 = last_d1
            self.last_d2 = last_d2
            self.last_error = None

            return {
                "pressure_mbar": avg_pressure,
                "temperature_c": avg_temp,
                "gauge_mbar": gauge,
                "depth_m": depth,
                "d1": last_d1,
                "d2": last_d2,
                "samples_taken": count,
            }
        finally:
            self.reading = False

    def _update_measurement(self):
        # Background periodic sampling (1 sample per timer tick)
        if self.reading:
            return False

        self.reading = True
        try:
            data = self._read_once()

            filtered = self._apply_filter(data["pressure_mbar"])
            gauge = None
            if self.zero_pressure_mbar is not None:
                gauge = filtered - self.zero_pressure_mbar

            depth = None
            if gauge is not None:
                # 1 mbar = 100 Pa
                depth = (gauge * 100.0) / (self.fluid_density * 9.80665)

            self.last_pressure_mbar = filtered
            self.last_temperature_c = data["temperature_c"]
            self.last_gauge_mbar = gauge
            self.last_depth_m = depth
            self.last_d1 = data["d1"]
            self.last_d2 = data["d2"]
            self.last_error = None

            return True
        finally:
            self.reading = False

    def _convert_pressure(self, mbar):
        if self.pressure_unit == "mbar":
            return mbar
        if self.pressure_unit == "bar":
            return mbar / 1000.0
        if self.pressure_unit == "kPa":
            return mbar / 10.0
        if self.pressure_unit == "Pa":
            return mbar * 100.0
        if self.pressure_unit == "psi":
            return mbar * 0.0145037738
        return mbar

    # ---------- Klipper lifecycle ----------

    def _handle_ready(self):
        if self.auto_start:
            self.reactor.update_timer(
                self.sample_timer,
                self.reactor.monotonic() + self.sample_interval
            )

    def _sample_timer(self, eventtime):
        try:
            if not self.reading:
                self._update_measurement()
        except Exception as e:
            self.last_error = str(e)
            self.initialized = False

        return eventtime + self.sample_interval

    # ---------- G-code ----------

    def cmd_MS_PRESSURE_QUERY(self, gcmd):
        try:
            samples_arg = gcmd.get_int("SAMPLES", None, minval=1, maxval=100)

            # If user explicitly passed SAMPLES, or auto_start is False, or no cached sample exists:
            if samples_arg is not None or not self.auto_start or self.last_pressure_mbar is None:
                count = samples_arg if samples_arg is not None else (self.filter_samples if not self.auto_start else 1)
                res = self._read_burst_samples(count)
                samples_used = res["samples_taken"]
            else:
                samples_used = len(self.samples) if self.samples else 1

            if self.last_pressure_mbar is None:
                err = self.last_error or "sensor not responding"
                raise gcmd.error("MS5837 read failed: %s" % err)

            p = self._convert_pressure(self.last_pressure_mbar)
            lines = [
                "MS5837 %s" % self.name,
                "Model: %s" % self.model,
                "Pressure Absolute: %.3f %s" % (p, self.pressure_unit),
                "Temperature: %.2f C" % self.last_temperature_c,
            ]

            if self.last_gauge_mbar is None:
                lines.append("Gauge Pressure: not zeroed")
            else:
                gp = self._convert_pressure(self.last_gauge_mbar)
                lines.append(
                    "Gauge Pressure: %.3f %s" % (gp, self.pressure_unit)
                )

            if self.last_depth_m is not None:
                lines.append("Depth: %.4f m" % self.last_depth_m)

            lines.extend([
                "Samples: %d" % samples_used,
                "D1: %d" % self.last_d1,
                "D2: %d" % self.last_d2,
                "CRC: %s" % ("OK" if self.crc_ok else "FAIL"),
            ])

            gcmd.respond_info("\n".join(lines))

        except Exception as e:
            self.last_error = str(e)
            raise gcmd.error("MS5837 read failed: %s" % e)

    def cmd_MS_PRESSURE_ZERO(self, gcmd):
        try:
            samples_arg = gcmd.get_int("SAMPLES", self.filter_samples, minval=1, maxval=100)
            self._read_burst_samples(samples_arg)

            if self.last_pressure_mbar is None:
                err = self.last_error or "sensor not responding"
                raise gcmd.error("MS5837 zero failed: %s" % err)

            self.zero_pressure_mbar = self.last_pressure_mbar
            self.last_gauge_mbar = 0.0
            self.last_depth_m = 0.0

            zp = self._convert_pressure(self.zero_pressure_mbar)
            gcmd.respond_info(
                "MS5837 %s zero reference set to %.3f %s (averaged over %d samples)"
                % (self.name, zp, self.pressure_unit, samples_arg)
            )
        except Exception as e:
            self.last_error = str(e)
            raise gcmd.error("MS5837 zero failed: %s" % e)

    def cmd_MS_PRESSURE_STATUS(self, gcmd):
        lines = [
            "MS5837 %s status" % self.name,
            "Model: %s" % self.model,
            "Initialized: %s" % ("yes" if self.initialized else "no"),
            "CRC: %s" % ("OK" if self.crc_ok else "FAIL"),
            "PROM: %s" % " ".join("%04X" % x for x in self.prom),
            "Auto start: %s" % ("yes" if self.auto_start else "no"),
            "Filter samples: %d" % self.filter_samples,
            "Sample interval: %.3f s" % self.sample_interval,
            "Fluid density: %.3f kg/m^3" % self.fluid_density,
        ]

        if self.zero_pressure_mbar is None:
            lines.append("Zero reference: not set")
        else:
            zp = self._convert_pressure(self.zero_pressure_mbar)
            lines.append(
                "Zero reference: %.3f %s (%.3f mbar)"
                % (zp, self.pressure_unit, self.zero_pressure_mbar)
            )

        if self.last_error:
            lines.append("Last error: %s" % self.last_error)
        else:
            lines.append("Last error: none")

        gcmd.respond_info("\n".join(lines))

    # ---------- Status API ----------

    def get_status(self, eventtime):
        return {
            "name": self.name,
            "model": self.model,
            "initialized": self.initialized,
            "crc_ok": self.crc_ok,
            "pressure_mbar": self.last_pressure_mbar,
            "pressure_gauge_mbar": self.last_gauge_mbar,
            "temperature_c": self.last_temperature_c,
            "depth_m": self.last_depth_m,
            "zero_pressure_mbar": self.zero_pressure_mbar,
            "d1": self.last_d1,
            "d2": self.last_d2,
            "last_error": self.last_error,
        }


def load_config(config):
    return MS5837Sensor(config)


def load_config_prefix(config):
    return MS5837Sensor(config)
