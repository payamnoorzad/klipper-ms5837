# Klipper MS5837

Klipper extension for the **TE Connectivity MS5837** pressure sensor family.

Current support:

- MS5837-02BA and MS5837-30BA
- I2C via Klipper MCU hardware I2C or software I2C
- Absolute pressure
- Gauge / zeroed pressure
- Temperature
- Moving-average filtering
- Depth calculation
- PROM calibration read
- CRC4 status
- G-code query / zero / status commands
- Klipper status export for Moonraker / Fluidd / Mainsail
- Single or multi-sensor config using `[ms5837]` or `[ms5837 <name>]`

## Wiring example: RP2040-Zero

Example wiring:

| MS5837 breakout | RP2040-Zero |
|---|---|
| VIN | 3V3 |
| GND | GND |
| SDA | GP0 |
| SCL | GP1 |

For the GY-37 / MS5837-02BA breakout, 3.3 V is a good choice when used with RP2040 logic.

If the breakout does not include I2C pull-ups, add pull-up resistors from SDA and SCL to 3.3 V.

## Installation

```bash
git clone https://github.com/payamnoorzad/klipper-ms5837.git ~/klipper-ms5837
cd ~/klipper-ms5837
./install.sh
```

Then restart Klipper:

```text
RESTART
```

## Example configuration

Software I2C on RP2040 GPIO0/GPIO1:

```ini
[ms5837 chamber_pressure]
model: 02BA
i2c_software_sda_pin: gpio0
i2c_software_scl_pin: gpio1
i2c_address: 118
i2c_speed: 100000

pressure_unit: mbar
sample_interval: 0.5
filter_samples: 5
fluid_density: 997
auto_start: True
```

Hardware I2C example:

```ini
[ms5837 chamber_pressure]
model: 02BA
i2c_bus: i2c0a
i2c_address: 118
i2c_speed: 100000
```

If the sensor is connected to a secondary MCU:

```ini
[ms5837 chamber_pressure]
model: 02BA
i2c_mcu: rp2040
i2c_bus: i2c0a
i2c_address: 118
```

## G-code command naming

Klipper's G-code parser does not reliably parse digits in extended command
names. For that reason, this extension intentionally uses:

```text
MS_PRESSURE_QUERY
MS_PRESSURE_ZERO
MS_PRESSURE_STATUS
```

instead of command names beginning with `MS5837_`.

## Commands

Read sensor (instantaneous or averaged over $N$ fresh burst samples):

```text
MS_PRESSURE_QUERY SENSOR=chamber_pressure
MS_PRESSURE_QUERY SENSOR=chamber_pressure SAMPLES=5
```

Set the current pressure as gauge zero reference (averaged over $N$ samples to eliminate noise):

```text
MS_PRESSURE_ZERO SENSOR=chamber_pressure
MS_PRESSURE_ZERO SENSOR=chamber_pressure SAMPLES=10
```

Show status and calibration data:

```text
MS_PRESSURE_STATUS SENSOR=chamber_pressure
```

Example output:

```text
MS5837 chamber_pressure
Model: 02BA
Pressure Absolute: 1001.235 mbar
Temperature: 27.42 C
Gauge Pressure: 3.115 mbar
Depth: 0.0319 m
Samples: 5
D1: 6508123
D2: 8667001
CRC: OK
```

## Pressure units

Supported config values:

```ini
pressure_unit: mbar
pressure_unit: bar
pressure_unit: kpa
pressure_unit: pa
pressure_unit: psi
```

## Gauge pressure

The sensor reports absolute pressure. To convert this into gauge pressure, run:

```text
MS_PRESSURE_ZERO SENSOR=chamber_pressure
```

Example:

```text
Before zero:
Absolute: 999.94 mbar

After zero:
Gauge: 0.00 mbar

Apply pressure:
Absolute: 1003.50 mbar
Gauge: 3.56 mbar
```

## Depth

Depth is calculated from zeroed pressure using:

```text
depth = pressure_difference / (density * gravity)
```

Default fluid density is:

```ini
fluid_density: 997
```

which is approximately fresh water near room temperature.

For seawater you can use a value around:

```ini
fluid_density: 1025
```

## Moonraker / API status

The module exposes status fields through Klipper's object status system.

Typical fields:

```text
pressure_mbar
pressure_gauge_mbar
temperature_c
depth_m
crc_ok
initialized
last_error
```

## Moonraker Update Manager

After cloning this repository, you may add an Update Manager entry similar to:

```ini
[update_manager klipper-ms5837]
type: git_repo
path: ~/klipper-ms5837
origin: https://github.com/payamnoorzad/klipper-ms5837.git
managed_services: klipper
```


## Troubleshooting

### NACK / START_NACK

If Klipper reports:

```text
I2C read failed to addr 118 with status NACK
```

check:

- sensor power
- shared ground
- SDA / SCL wiring
- correct I2C bus
- pull-up resistors
- correct MCU selection

The MS5837 uses I2C address:

```text
0x76 = 118 decimal
```

### PROM works but later reads fail

The sensor requires a delay after reset and ADC conversion. This extension already includes the required timing margins.

## License

MIT
