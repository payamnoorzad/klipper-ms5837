# Wiring

## RP2040-Zero

Recommended initial wiring:

```text
MS5837 / GY-37      RP2040-Zero

VIN   ------------> 3V3
GND   ------------> GND
SDA   ------------> GP0
SCL   ------------> GP1
```

Software-I2C config:

```ini
[ms5837 chamber_pressure]
model: 02BA
i2c_software_sda_pin: gpio0
i2c_software_scl_pin: gpio1
i2c_address: 118
i2c_speed: 100000
```

Hardware-I2C config can be used if the Klipper MCU build exposes the selected RP2040 I2C bus:

```ini
[ms5837 chamber_pressure]
model: 02BA
i2c_bus: i2c0a
i2c_address: 118
i2c_speed: 100000
```

The MS5837 I2C address is fixed at `0x76` (`118` decimal).
