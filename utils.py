import json
import os
import random
import string
import hashlib
from datetime import datetime, timedelta

import backoff
import requests
from requests import RequestException
from math import radians, sin, cos, sqrt, atan2


def string_to_dark_background_color(input_string: str) -> tuple[int, int, int]:
    # Use hashlib to generate a hash based on the input string
    hash_object = hashlib.md5(input_string.encode())
    hash_hex = hash_object.hexdigest()

    # Take the first 6 characters of the hash to get an RGB value
    hex_color = hash_hex[:6]

    # Convert hex to RGB and ensure darker shades
    red = int(hex_color[0:2], 16) % 128
    green = int(hex_color[2:4], 16) % 128
    blue = int(hex_color[4:6], 16) % 128

    return red, green, blue


def haversine(lat1, lon1, lat2, lon2):
    # Convert latitude and longitude from degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    a = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    # Radius of Earth in kilometers (approximate)
    r = 6371.0

    # Calculate distance
    distance = r * c

    return distance


def get_lat_long_from_string_address(address: str) -> tuple[float, float]:
    nominatim_endpoint = "https://nominatim.openstreetmap.org/search"
    params = {
        "format": "json",
        "q": address,
    }
    response = requests.get(nominatim_endpoint, params=params)
    data = response.json()

    if not data:
        print("No location found for the given address.")
        return 0.0, 0.0

    # Assuming the first result is the desired location
    location = data[0]
    return float(location["lat"]), float(location["lon"])


@backoff.on_exception(backoff.expo, RequestException, jitter=backoff.full_jitter)
def get_nearby_routes(api_key: str, lat_long: tuple[float, float]) -> list:
    search_radius_meters = int(os.getenv("SEARCH_RADIUS_METERS", "300"))
    params = {
        "lat": lat_long[0],
        "lon": lat_long[1],
        "radius": search_radius_meters,  # Radius in meters (adjust as needed),
        "limit": 100,
    }
    transitland_endpoint = "https://transit.land/api/v2/rest/routes"
    response = requests.get(
        transitland_endpoint, params=params, headers={"apikey": api_key}
    )
    print(response)
    response.raise_for_status()
    json_data = response.json()
    if not json_data:
        return []
    return json_data["routes"]


@backoff.on_exception(backoff.expo, RequestException, jitter=backoff.full_jitter)
def get_nearby_stops(api_key: str, lat_long: tuple[float, float]) -> list:
    search_radius_meters = int(os.getenv("SEARCH_RADIUS_METERS", "300"))
    params = {
        "lat": lat_long[0],
        "lon": lat_long[1],
        "radius": search_radius_meters,  # Radius in meters (adjust as needed),
        "limit": 100,
    }
    transitland_endpoint = "https://transit.land/api/v2/rest/stops"
    response = requests.get(
        transitland_endpoint, params=params, headers={"apikey": api_key}
    )
    response.raise_for_status()
    json_data = response.json()
    if not json_data:
        return []
    return json_data["stops"]


def get_corrected_datetime(service_date: str, arrival_time: str) -> datetime:
    # Parsing the service_date
    arrival_date = datetime.strptime(service_date, "%Y-%m-%d")

    # Parsing the arrival_time
    hour, minute, second = map(int, arrival_time.split(":"))

    # Check if the hour is greater than 23
    if hour > 23:
        # Increment the arrival_date by one day
        arrival_date += timedelta(days=1)
        # Set the hour to the remainder after subtracting 24
        hour = hour % 24

    # Set the time components
    return arrival_date.replace(hour=hour, minute=minute, second=second)


@backoff.on_exception(backoff.expo, RequestException, jitter=backoff.full_jitter)
def get_departures_for_stop_id(
    api_key: str, stop_id: str, next_sec: int = None
) -> list:
    print(f"getting upcoming departures for: {stop_id}")
    transitland_endpoint = (
        f"https://transit.land/api/v2/rest/stops/{stop_id}/departures"
    )
    params = {"next": 86400 if not next_sec else next_sec}  # TODO?
    response = requests.get(
        transitland_endpoint, params=params, headers={"apikey": api_key}
    )
    # print(response)
    response.raise_for_status()
    return response.json()["stops"][0]["departures"]


def get_next_departures_for_stop_list(
    api_key: str,
    stops: list[dict],
    starting_coords: tuple[float, float],
    hours: int = 1,
) -> dict:
    departures = {}

    for stop in stops:
        departures_for_stop = get_departures_for_stop_id(
            api_key, stop["id"], next_sec=(3600 * hours)
        )
        for stop_departure in departures_for_stop:
            trip_id = stop_departure["trip"]["id"]
            stop_point = stop["geometry"]["coordinates"]
            user_distance_from_stop = haversine(
                starting_coords[0], starting_coords[1], stop_point[1], stop_point[0]
            )

            realtime_arrival_time = stop_departure["arrival"]["estimated"]
            scheduled_arrival_time = stop_departure["arrival"]["scheduled"]
            if realtime_arrival_time:
                realtime_data = True
                arrival_time = realtime_arrival_time
            else:
                realtime_data = False
                arrival_time = scheduled_arrival_time

            if trip_id not in departures.keys():
                arrival_datetime = get_corrected_datetime(
                    stop_departure["service_date"], arrival_time
                )

                departures[trip_id] = {
                    "departure": stop_departure,
                    "closest_stop": stop,
                    "distance": user_distance_from_stop,
                    "arrival_time": arrival_datetime,
                    "realtime_data": realtime_data,
                }

            else:
                print(
                    f"Already tracking trip {trip_id} (Route {stop_departure['trip']['route']['route_short_name']} "
                    f"towards {stop_departure['trip']['trip_headsign']})"
                )
                print(
                    f"Checking if this stop ({stop['stop_name']}) is closer than what is currently cached "
                    f"({departures[trip_id]['closest_stop']['stop_name']})"
                )
                current_distance_from_cached_stop = departures[trip_id]["distance"]

                if user_distance_from_stop < current_distance_from_cached_stop:
                    print("It is closer, updating cache")

                    arrival_datetime = datetime.strptime(
                        f"{stop_departure['service_date']} {arrival_time}",
                        "%Y-%m-%d %H:%M:%S",
                    )
                    departures[trip_id] = {
                        "departure": stop_departure,
                        "closest_stop": stop,
                        "distance": user_distance_from_stop,
                        "arrival_time": arrival_datetime,
                        "realtime_data": realtime_data,
                    }

                else:
                    print("It is NOT closer, continuing")

    return departures


def print_schedule(display: dict):
    os.system("cls")
    print(json.dumps(display, default=str, indent=1))


def time_difference_strings(date_list, realtime_data=None):
    current_time = datetime.now()

    time_strings = []

    for date_index, date in enumerate(date_list):
        time_difference = date - current_time
        minutes_difference = int(time_difference.total_seconds() / 60)

        if minutes_difference == 0:
            time_string_to_add = "Now"
        else:
            time_string_to_add = f"{abs(minutes_difference)} min"

        if realtime_data and realtime_data[date_index]:
            time_string_to_add = f"{time_string_to_add}*"

        time_strings.append(time_string_to_add)

    return time_strings


def time_difference_strings(date_list, realtime_data=None):
    current_time = datetime.now()

    time_strings = []

    for date_index, date in enumerate(date_list):
        time_difference = date - current_time
        minutes_difference = int(time_difference.total_seconds() / 60)

        if minutes_difference == 0:
            time_string_to_add = "Now"
        else:
            time_string_to_add = f"{abs(minutes_difference)} min"

        if realtime_data and realtime_data[date_index]:
            time_string_to_add = f"{time_string_to_add}📡"

        time_strings.append(time_string_to_add)

    return time_strings


def generate_random_string(length=8):
    characters = string.ascii_letters + string.digits
    random_string = "".join(random.choice(characters) for _ in range(length))
    return random_string


def generate_randomized_data(num_routes=5, num_stops=5, num_arrival_times=3):
    print("generating garbage data")
    routes = [f"{i}" for i in range(1, num_routes + 1)]
    stops = [f"Stop {i}" for i in range(1, num_stops + 1)]

    display_data = {}

    for route in routes:
        direction = generate_random_string(8)
        stop = random.choice(stops)

        arrival_times = []
        realtime_data = []

        for _ in range(num_arrival_times):
            arrival_time = datetime.now() - timedelta(minutes=random.randint(1, 120))
            arrival_times.append(arrival_time)
            realtime_data.append(random.choice([True, False]))

        display_data[f"{route} - {direction}"] = {
            "route": route,
            "direction": direction,
            "stop": stop,
            "arrival_times": arrival_times,
            "realtime_data": realtime_data,
        }

    return display_data


def get_upcoming_departures(
    api_key: str, stop_list: list[dict], address_geo_coords: tuple[float, float]
) -> tuple[dict, list[dict]]:
    # Get ALL departures for the stop list arg and sort them by arrival time
    all_departures = get_next_departures_for_stop_list(
        api_key, stop_list, address_geo_coords
    )
    sorted_departures = dict(
        sorted(all_departures.items(), key=lambda item: item[1]["arrival_time"])
    )

    departure_dict = {}
    for trip_id, trip_vals in sorted_departures.items():
        # Parse out values from the sorted departure for use in the UI list
        departure = trip_vals["departure"]
        agency_name = departure["trip"]["route"]["agency"]["agency_name"]
        closest_stop = trip_vals["closest_stop"]
        distance_from_user = trip_vals["distance"]
        arrival_datetime = trip_vals["arrival_time"]
        realtime_data = trip_vals["realtime_data"]
        route_headsign_combo = (
            f"{departure['trip']['route']['route_short_name']} - "
            f"{departure['trip']['trip_headsign']}"
        )

        # Log for debugging
        print(
            f"Monitoring trip {trip_id} (Route {route_headsign_combo}) from stop {closest_stop['stop_name']} "
            f"at {distance_from_user} distance from user address and arrives at {departure['arrival_time']}"
        )

        # Store entry under headsign combo key
        if route_headsign_combo not in departure_dict.keys():
            departure_dict[route_headsign_combo] = {
                "route": departure["trip"]["route"]["route_short_name"],
                "route_type": gtfs_route_type_to_string(
                    departure["trip"]["route"]["route_type"]
                ),
                "direction": departure["trip"]["trip_headsign"],
                "stop": closest_stop["stop_name"],
                "arrival_times": [arrival_datetime],
                "realtime_data": [realtime_data],
                "agency_name": agency_name,
                "full_stop": closest_stop,
            }

        # If it already is stored, add the arrival time to the list, max of 4 for now
        else:
            if len(departure_dict[route_headsign_combo]["arrival_times"]) < 4:
                departure_dict[route_headsign_combo]["arrival_times"].append(
                    arrival_datetime
                )
                departure_dict[route_headsign_combo]["realtime_data"].append(
                    realtime_data
                )

    # List to store only stops worth monitoring (closest to location for a given route + direction combo)
    updated_stop_list = []
    for _, departure_values in departure_dict.items():
        if not any(
            stop_list_entry["id"] == departure_values["full_stop"]["id"]
            for stop_list_entry in updated_stop_list
        ):
            updated_stop_list.append(departure_values["full_stop"])

    return departure_dict, updated_stop_list


def gtfs_route_type_to_string(route_type_int: int) -> str:
    """
    0 - Tram, Streetcar, Light rail. Any light rail or street level system within a metropolitan area.
    1 - Subway, Metro. Any underground rail system within a metropolitan area.
    2 - Rail. Used for intercity or long-distance travel.
    3 - Bus. Used for short- and long-distance bus routes.
    4 - Ferry. Used for short- and long-distance boat service.
    5 - Cable tram. Used for street-level rail cars where the cable runs beneath the vehicle, e.g., cable car in San
        Francisco.
    6 - Aerial lift, suspended cable car (e.g., gondola lift, aerial tramway). Cable transport where cabins, cars,
        gondolas or open chairs are suspended by means of one or more cables.
    7 - Funicular. Any rail system designed for steep inclines.
    11 - Trolleybus. Electric buses that draw power from overhead wires using poles.
    12 - Monorail. Railway in which the track consists of a single rail or a beam.
    """

    route_type_to_string_mapping = {
        0: "Trolley 🚋",
        1: "Subway 🚇",
        2: "Train 🚆",
        3: "Bus 🚍",
        4: "Ferry ⛴️",
        5: "Cable Tram 🚋",
        6: "Aerial Lift 🚠",
        7: "Funicular 🚡",
        11: "TrolleyBus 🚎",
        12: "Monorail 🚝",
    }

    return route_type_to_string_mapping[route_type_int]


def simplify_route_name(route_name: str) -> str:
    route_name = route_name.replace(" Line", "")
    route_name = route_name.replace("/", "\n")
    return route_name
