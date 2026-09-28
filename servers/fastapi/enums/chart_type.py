from enum import Enum


class ChartType(str, Enum):
    BAR = "bar"
    HORIZONTAL_BAR = "horizontal_bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    DONUT = "donut"
    STACKED_BAR = "stacked_bar"
    HORIZONTAL_STACKED_BAR = "horizontal_stacked_bar"
    SCATTER = "scatter"
    RADAR = "radar"
    POLAR_AREA = "polar_area"
