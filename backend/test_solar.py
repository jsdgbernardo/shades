"""PRD D-02: the sun position must match a trusted reference within 1 degree.

The reference is the NOAA Solar Calculator spreadsheet algorithm (Meeus-based, the method
behind NOAA's online calculator), implemented here independently of ``shade.solar_position``,
which uses NOAA's shorter "general solar position" equations. Elevation is compared without
atmospheric refraction, which is below 0.1 degree at the elevations tested.
"""

import math
import unittest
from datetime import datetime, timezone

from shade import solar_position

ADMU = (14.6397, 121.0781)


def noaa_reference(when_utc: datetime, latitude: float, longitude: float) -> tuple[float, float]:
    rad, deg = math.radians, math.degrees
    julian_day = when_utc.timestamp() / 86400 + 2440587.5
    jc = (julian_day - 2451545) / 36525
    mean_long = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    eccent = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    center = (math.sin(rad(mean_anom)) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
              + math.sin(rad(2 * mean_anom)) * (0.019993 - 0.000101 * jc)
              + math.sin(rad(3 * mean_anom)) * 0.000289)
    true_long = mean_long + center
    app_long = true_long - 0.00569 - 0.00478 * math.sin(rad(125.04 - 1934.136 * jc))
    mean_obliq = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obliq = mean_obliq + 0.00256 * math.cos(rad(125.04 - 1934.136 * jc))
    declination = deg(math.asin(math.sin(rad(obliq)) * math.sin(rad(app_long))))
    var_y = math.tan(rad(obliq / 2)) ** 2
    eq_time = 4 * deg(
        var_y * math.sin(2 * rad(mean_long)) - 2 * eccent * math.sin(rad(mean_anom))
        + 4 * eccent * var_y * math.sin(rad(mean_anom)) * math.cos(2 * rad(mean_long))
        - 0.5 * var_y * var_y * math.sin(4 * rad(mean_long)) - 1.25 * eccent * eccent * math.sin(2 * rad(mean_anom))
    )
    utc_minutes = when_utc.hour * 60 + when_utc.minute + when_utc.second / 60
    true_solar = (utc_minutes + eq_time + 4 * longitude) % 1440
    hour_angle = true_solar / 4 + 180 if true_solar / 4 < 0 else true_solar / 4 - 180
    zenith = deg(math.acos(math.sin(rad(latitude)) * math.sin(rad(declination))
                           + math.cos(rad(latitude)) * math.cos(rad(declination)) * math.cos(rad(hour_angle))))
    cos_az = ((math.sin(rad(latitude)) * math.cos(rad(zenith)) - math.sin(rad(declination)))
              / (math.cos(rad(latitude)) * math.sin(rad(zenith))))
    cos_az = max(-1.0, min(1.0, cos_az))
    if hour_angle > 0:
        azimuth = (deg(math.acos(cos_az)) + 180) % 360
    else:
        azimuth = (540 - deg(math.acos(cos_az))) % 360
    return 90 - zenith, azimuth


class SolarPositionTests(unittest.TestCase):
    def check(self, local_iso: str):
        elevation, azimuth = solar_position(local_iso, *ADMU)
        when_utc = datetime.fromisoformat(local_iso).astimezone(timezone.utc)
        ref_elevation, ref_azimuth = noaa_reference(when_utc, *ADMU)
        self.assertAlmostEqual(elevation, ref_elevation, delta=1.0, msg=f"elevation at {local_iso}")
        azimuth_error = abs((azimuth - ref_azimuth + 180) % 360 - 180)
        self.assertLessEqual(azimuth_error, 1.0, msg=f"azimuth at {local_iso}: {azimuth} vs {ref_azimuth}")

    def test_morning_noon_afternoon_within_one_degree(self):
        for day in ("2026-03-20", "2026-06-21", "2026-10-15", "2026-12-21"):
            for hour in ("09:00", "12:00", "15:00"):
                with self.subTest(day=day, hour=hour):
                    self.check(f"{day}T{hour}:00+08:00")

    def test_sun_is_east_in_morning_and_west_in_afternoon(self):
        _, morning = solar_position("2026-10-15T09:00:00+08:00", *ADMU)
        _, afternoon = solar_position("2026-10-15T15:00:00+08:00", *ADMU)
        self.assertTrue(45 < morning < 180)
        self.assertTrue(180 < afternoon < 315)


if __name__ == "__main__":
    unittest.main()
