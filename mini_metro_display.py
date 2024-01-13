import os
import sys
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QThread
from PyQt5.QtGui import QPainter, QPainterPath, QColor, QFont, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QStackedWidget,
    QHBoxLayout,
    QGridLayout,
)

from utils import (
    get_nearby_stops,
    get_nearby_routes,
    get_lat_long_from_string_address,
    get_upcoming_departures,
    time_difference_strings,
    string_to_dark_background_color,
    simplify_route_name,
)

PAGE_TURN_INTERVAL_SEC = 15
DISPLAY_UPDATE_INTERVAL_SEC = 120
UPDATE_INTERVALS_TO_USE_CACHED_STOP_DATA = 30


class WorkerThread(QThread):
    def __init__(
        self,
        transitland_api_key: str,
        monitored_stop_list: list[dict],
        address_coords: tuple[float, float],
    ):
        super(WorkerThread, self).__init__()
        self.transitland_api_key = transitland_api_key
        self.monitored_stop_list = (
            monitored_stop_list  # initial stop list brought over from main
        )
        self.address_coords = address_coords
        self.update_intervals_to_use_cached_stop_data = (
            UPDATE_INTERVALS_TO_USE_CACHED_STOP_DATA
        )

    data_updated = pyqtSignal(dict)

    def run(self):
        while True:
            # Get upcoming departure data in display ready format, get updated stops list we used for this data
            display_data, updated_stops_list = get_upcoming_departures(
                self.transitland_api_key, self.monitored_stop_list, self.address_coords
            )

            # Update the monitored stops list to only the stops we used for the current data
            if self.update_intervals_to_use_cached_stop_data != 0:
                self.monitored_stop_list = updated_stops_list
                print(
                    f"currently monitoring {len(self.monitored_stop_list)} stops with {len(display_data)} departures"
                )
                print(
                    f"{self.update_intervals_to_use_cached_stop_data} more updates "
                    f"before we refresh monitored stop list"
                )
                self.update_intervals_to_use_cached_stop_data -= 1
            else:
                # Refresh the stop list to start over from all nearby stops again to handle newly added routes etc.
                print("refreshing all monitored stops (to handle newly added routes)")
                self.monitored_stop_list = get_nearby_stops(
                    self.transitland_api_key, self.address_coords
                )
                self.update_intervals_to_use_cached_stop_data = (
                    UPDATE_INTERVALS_TO_USE_CACHED_STOP_DATA
                )

            # display_data = generate_randomized_data(num_routes=random.randint(11, 20), num_stops=random.randint(3, 9))
            print("done generating data, updating the UI")
            self.data_updated.emit(display_data)

            self.msleep(DISPLAY_UPDATE_INTERVAL_SEC * 1000)


class PageIndicator(QWidget):
    def __init__(self, parent=None, total_pages=0):
        super(PageIndicator, self).__init__(parent)
        self.total_pages = total_pages
        self.current_page = 0

    def set_current_page(self, current_page):
        self.current_page = current_page
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        dot_radius = 5
        dot_spacing = 5
        hollow_dot_color = QColor(255, 255, 255)

        path = QPainterPath()

        for i in range(self.total_pages):
            x = i * (dot_radius * 2 + dot_spacing)
            y = 0

            painter.setBrush(hollow_dot_color)
            painter.setPen(Qt.NoPen)
            path.addEllipse(x, y, dot_radius * 2, dot_radius * 2)
            painter.setBrush(hollow_dot_color)
            path.addEllipse(x, y, dot_radius * 2, dot_radius * 2)

        if self.total_pages > 0:
            current_x = self.current_page * (dot_radius * 2 + dot_spacing)
            painter.setBrush(hollow_dot_color)
            path.addEllipse(current_x, y, dot_radius * 2, dot_radius * 2)

        painter.drawPath(path)


class BusStopApp(QWidget):
    def __init__(
        self,
        transitland_api_key: str,
        monitored_stop_list: list[dict],
        address_coords: tuple[float, float],
    ):
        super(BusStopApp, self).__init__()

        self.departure_info = {}
        self.current_page = 0

        self.stacked_widget = QStackedWidget(self)

        self.page_indicator = PageIndicator(total_pages=0)
        self.page_indicator.setFixedSize(100, 20)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.switch_page)
        self.timer.start(PAGE_TURN_INTERVAL_SEC * 1000)

        self.signal_emitter = WorkerThread(
            transitland_api_key, monitored_stop_list, address_coords
        )
        self.signal_emitter.data_updated.connect(self.update_table)
        self.signal_emitter.start()

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(self.stacked_widget)

        page_indicator_layout = QHBoxLayout()
        page_indicator_layout.addStretch()
        page_indicator_layout.addWidget(self.page_indicator)
        page_indicator_layout.addStretch()

        layout.addLayout(page_indicator_layout)
        self.showMaximized()

    def switch_page(self):
        total_pages = self.stacked_widget.count()

        if total_pages > 1:
            self.current_page = (self.current_page + 1) % total_pages
            self.stacked_widget.setCurrentIndex(self.current_page)
            self.page_indicator.set_current_page(self.current_page)
            print(f"Current Page: {self.current_page + 1}")

    def update_table(self, display_data):
        self.departure_info = display_data
        for i in reversed(range(self.stacked_widget.count())):
            self.stacked_widget.removeWidget(self.stacked_widget.widget(i))

        items_per_page = 4
        total_departures = len(self.departure_info)
        total_pages = (total_departures + items_per_page - 1) // items_per_page

        self.page_indicator.total_pages = total_pages
        self.page_indicator.set_current_page(self.current_page)

        for page in range(total_pages):
            start_index = page * items_per_page
            end_index = min((page + 1) * items_per_page, total_departures)

            page_widget = QWidget()
            layout = QVBoxLayout(page_widget)

            for route_headsign_combo, info in list(self.departure_info.items())[
                start_index:end_index
            ]:
                row_widget = QWidget()

                row_layout = QGridLayout(row_widget)

                route_icon = QLabel()
                route_icon.setStyleSheet(
                    "QLabel { background-color : transparent; color : white; }"
                )
                route_icon.setAlignment(Qt.AlignCenter)
                route_icon_text = simplify_route_name(info.get("route", ""))

                # Calculate the size dynamically based on the available space
                icon_size = min(
                    self.width() // 20, row_widget.height()
                )  # Adjust the denominator for desired scaling

                # Create a circular QPixmap
                pixmap = QPixmap(icon_size, icon_size)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                random_color = QColor(*string_to_dark_background_color(route_icon_text))
                painter.setBrush(random_color)
                painter.drawEllipse(0, 0, icon_size, icon_size)
                painter.setPen(Qt.white)

                # Calculate font size based on window width
                font_size = (
                    self.width() // 60
                )  # Adjust the denominator for desired scaling

                font = QFont()
                font.setPixelSize(font_size)

                painter.setFont(font)
                painter.drawText(
                    0, 0, icon_size, icon_size, Qt.AlignCenter, route_icon_text
                )
                painter.end()

                route_icon.setPixmap(pixmap)
                route_icon.setFixedSize(icon_size, icon_size)

                label_text = f"{info.get('agency_name', '')} {info.get('route_type', '')}\nto {info.get('direction', '')}"
                label = QLabel(label_text)
                label.setAlignment(Qt.AlignLeft)
                label.setStyleSheet("color: white;")
                label.setFont(font)

                label_text2 = f"Closest Stop:\n{info.get('stop', '')}"
                label2 = QLabel(label_text2)
                label2.setAlignment(Qt.AlignLeft)
                label2.setStyleSheet("color: white;")
                label2.setFont(font)

                label_text3 = f"{time_difference_strings(info.get('arrival_times', []), info.get('realtime_data', []))[0]}"
                if (
                    len(
                        time_difference_strings(
                            info.get("arrival_times", []), info.get("realtime_data", [])
                        )
                    )
                    > 1
                ):
                    label_text3 += (
                        "\nalso"
                        f" {',  '.join(time_difference_strings(info.get('arrival_times', []), info.get('realtime_data', []))[1:])}"
                    )

                label3 = QLabel(label_text3)
                label3.setAlignment(Qt.AlignLeft)
                label3.setStyleSheet("color: white;")
                label3.setFont(font)

                row_layout.addWidget(route_icon, 0, 0)
                row_layout.addWidget(label, 0, 1)
                row_layout.addWidget(label2, 0, 2)
                row_layout.addWidget(label3, 0, 3)

                layout.addWidget(row_widget)

            page_widget.setLayout(layout)
            self.stacked_widget.addWidget(page_widget)

        self.current_page = 0
        self.stacked_widget.setCurrentIndex(self.current_page)
        self.page_indicator.set_current_page(self.current_page)
        self.timer.start(PAGE_TURN_INTERVAL_SEC * 1000)


if __name__ == "__main__":
    # Attempt to grab environment variables
    transitland_api_key = os.getenv("TRANSITLAND_API_KEY")
    if not transitland_api_key:
        print(
            "Required TransitLand API key not found in env vars, "
            "please set it as TRANSITLAND_API_KEY and restart the app"
        )
        sys.exit(1)

    starting_address = os.getenv("STARTING_ADDRESS", "3401 Market St Philadelphia")
    search_radius_meters = int(os.getenv("SEARCH_RADIUS_METERS", "300"))

    # Initial setup/data gathering
    address_lat_long = get_lat_long_from_string_address(starting_address)
    print(
        f"Converted supplied address to geo-coordinates\n{starting_address} -> {address_lat_long}"
    )
    # Get locally served routes
    route_list = get_nearby_routes(transitland_api_key, address_lat_long)
    # route_list_detailed = {route['id']: get_route_details(key, route['id']) for route in route_list}

    # Get locally served stops
    stop_list = get_nearby_stops(transitland_api_key, address_lat_long)
    print(
        f"Within {search_radius_meters} meters of the provided address, there are {len(stop_list)} "
        f"transit stops, served by {len(route_list)} routes."
    )

    app = QApplication(sys.argv)
    window = BusStopApp(
        transitland_api_key=transitland_api_key,
        monitored_stop_list=stop_list,
        address_coords=address_lat_long,
    )
    window.show()
    sys.exit(app.exec_())
