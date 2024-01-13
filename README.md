## Mini Metro Display
A lightweight and configurable departures board to show nearby multi-modal transit routes, their upcoming departures (realtime & scheduled) and the nearest stop. 

Supports subways, buses, trains, trams, ferries, trolleys, cable cars, planes, and more! 

![mmd.gif](media%2Fmmd.gif)


### Configuration
#### Installing Dependencies
Install the dependencies of the project using `pip`:
```commandline
python3 -m pip install -r requirements.txt
```

#### Required Environment Variables
- `TRANSITLAND_API_KEY`(required) - TransitLand's free tier REST api key
- `STARTING_ADDRESS` - String of the starting address to find routes that serve the area
- `SEARCH_RADIUS_METERS` - Number of meters for a search radius for transit routes and stops

#### Running the app
Run the app by executing the main script:
```./mini_metro_display.py```

### Used Technologies
- [TransitLand](https://www.transit.land/documentation/index) - Route, stop, and schedule information via the v2 REST API endpoint
- [OpenStreetMap](https://nominatim.openstreetmap.org/ui/search.html) - Geocoding via the Nominatim endpoint 
