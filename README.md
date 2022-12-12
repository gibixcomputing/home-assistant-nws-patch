# NWSWeather Patch
This is a simple "custom component" that attempts to patch the existing
`nws` component. This patch changes how the forecast is generated to
better support the day/night aspects of the default weather card and to
make the forecasts simpler and easier.

This custom component provides no entities, sensors, or services. It
serves as just a "more proper" way to load and patch the existing `nws`
component at runtime without requiring any code changes to the
underlying installation. Due to the patching aspect, this may break with
any HA updates. If it does, the patch will revert back to the original
behavior.

## Minimum Supported HA Version
At the time of writing **2022.12.1** is the minimum supported version.
This is due to me only testing on this version and being really lazy
about testing older versions. It _may_ work all the way back to 2022.07
when the `native_temperature` et al. keys replaced the older
`temperature` keys.

## HACS Support
HACS support and availability is made on a best effort basis. I don't
use HACS myself so I don't keep up with making sure it works with every
version change.
