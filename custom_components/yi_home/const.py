"""Constants for the YI Home integration."""

DOMAIN = "yi_home"

CONF_API_TOKEN = "api_token"
CONF_RTSP_PORT = "rtsp_port"
CONF_REGION = "region"
CONF_COUNTRY = "country"
CONF_ACCOUNT = "account"

DEFAULT_PORT = 8099
DEFAULT_REGION = "eu"
DEFAULT_COUNTRY = "IL"

# Internal compatibility profile for the YI Home Android API contract. These
# fields are deliberately not exposed in the Home Assistant UI.
CLIENT_DEVICE_BRAND = "samsung"
CLIENT_DEVICE_MODEL = "SM-S901B"
CLIENT_ANDROID_VERSION = "13"
CLIENT_LANGUAGE = "en-US"
