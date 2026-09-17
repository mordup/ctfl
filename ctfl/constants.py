APP_NAME = "ctfl"
APP_DISPLAY_NAME = "Claude Tracker For Linux"
ICON_THEME_NAME = "ctfl"
DATE_FMT_ISO = "%Y-%m-%d"
TIME_FMT_HM = "%H:%M"
DATE_FMT_DISPLAY = "%-d %B"
DATETIME_FMT_WEEKDAY = "%a %H:%M"
# Claude Code deletes transcripts after cleanupPeriodDays (default 30). Older
# days would come from its stats cache, which counts each request per content
# block, so the window stops where the per-request data does.
MAX_DAYS_TO_SHOW = 30

# UI style tokens (only values reused across multiple widgets)
COLOR_ACCENT = "#5B9BF6"
COLOR_MUTED = "gray"
FONT_SIZE_SMALL = "11px"
