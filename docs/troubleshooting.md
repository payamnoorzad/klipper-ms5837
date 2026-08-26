# Troubleshooting

## I2C NACK

Typical error:

```text
MCU 'mcu' I2C read failed to addr 118 with status NACK
```

Check:

1. Sensor has power.
2. Ground is shared with the MCU.
3. SDA and SCL are not swapped.
4. The selected Klipper MCU is correct.
5. I2C pull-ups are present.
6. `i2c_address` is `118`.

## Stable PROM is a good sign

A repeated stable PROM result, for example:

```text
5001 B75A BC6F 6E31 7413 8092 685C
```

strongly indicates that the I2C path and sensor communication are working.

## Absolute pressure near 1000 mbar

This is normal in ambient air. The sensor reports absolute pressure.

Use:

```text
MS_PRESSURE_ZERO SENSOR=<name>
```

to work with gauge pressure relative to the current ambient pressure.
