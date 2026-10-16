# Weather-Aware Truck Routing

This is a full-stack route planning application for truck drivers. It compares several truck-compatible routes, checks the expected weather along each one, and recommends the safest option using the rules supplied with the assessment.

The backend is Django REST Framework. The frontend is React, TypeScript and Leaflet. Geoapify provides geocoding and heavy-truck routes, while Open-Meteo provides hourly weather forecasts.

## What the application does

The driver enters an origin, destination, departure time, cargo weight and checkpoint spacing. The application then:

1. Resolves both locations and requests up to three distinct heavy-truck routes.
2. Places checkpoints every 10, 25 or 50 miles along the actual route geometry.
3. Estimates when the truck will reach every checkpoint.
4. Fetches the forecast closest to each checkpoint ETA.
5. Applies the wind, rain, snow and cargo-weight rules.
6. Ranks safe routes by Severe miles, High miles, average risk and travel time.
7. Returns a 48-hour hourly forecast for the interactive corridor heatmap.

The map draws every route and displays weather checkpoints for the selected route. Moving the forecast slider updates the heat layer and checkpoint colors.

## Project layout

```text
Spotter-assessment/
├── frontend/                 React and Leaflet client
├── weather_truck_routing/    Django API
│   ├── trips/
│   │   ├── clients/          Geoapify and Open-Meteo adapters
│   │   ├── services/         Checkpoints, risk and recommendation logic
│   │   └── tests/
│   └── weather_truck_routing/
├── .env                      Local secrets (do not commit this file)
└── README.md
```

The calculation code is kept out of the API views. Risk classification, checkpoint placement and route ranking are pure services, which makes the important rules easier to test.

## Running it locally

You will need Python 3.11 or newer, Node.js 20.19 or newer, and a Geoapify API key.

### Backend

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r weather_truck_routing/requirements.txt
cp weather_truck_routing/.env.example .env
```

Open `.env` and set `GEOAPIFY_API_KEY`. Open-Meteo does not require an API key.

Then start Django:

```bash
cd weather_truck_routing
python manage.py migrate
python manage.py runserver
```

The API will be available at `http://localhost:8000/api/v1/`.

### Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

The client uses `http://localhost:8000/api/v1` by default. To use another backend, copy `frontend/.env.example` to `frontend/.env` and change `VITE_API_BASE_URL`.

## API endpoints

### Health check

```http
GET /api/v1/health/
```

### Location suggestions

```http
GET /api/v1/locations/search/?q=Lahore
```

The browser calls this endpoint instead of calling Geoapify directly, so the API key is never exposed to the frontend.

### Trip analysis

```http
POST /api/v1/trip-analyses/
Content-Type: application/json
```

Example request:

```json
{
  "origin": "Lahore, Pakistan",
  "destination": "Karachi, Pakistan",
  "departure_time": "2026-10-17T12:00:00Z",
  "cargo_weight_lb": 35000,
  "checkpoint_interval_miles": 25
}
```

The response contains resolved locations, route geometries, route summaries, checkpoint ETAs, ETA-matched weather, risk exposure and the hourly data used by the 0-48 hour slider.

## Risk rules

| Condition |              Low |  Moderate |      High |    Severe |       No Travel |
| --------- | ---------------: | --------: | --------: | --------: | --------------: |
| Wind      |     below 25 mph | 25-34 mph | 35-44 mph | 45-54 mph | 55 mph or above |
| Rain      | below 0.10 in/hr | 0.10-0.25 | 0.25-0.50 | 0.50-1.00 |      above 1.00 |
| Snow      |  below 0.5 in/hr |   0.5-1.0 |   1.0-2.0 |   2.0-3.0 |       above 3.0 |

Shared boundaries use the more serious category. For example, rain at exactly `0.25 in/hr` is High, exactly `0.50` is Severe, and exactly `1.00` remains Severe because No Travel begins above `1.00`.

Cargo weight changes the wind result in these cases:

- Wind at 55 mph or above is No Travel for every load.
- Wind from 45 through 54 mph with a load over 30,000 lb is No Travel.
- Wind from 35 through 44 mph with a load over 40,000 lb is Severe.

The overall checkpoint risk is the highest risk produced by wind, rain or snow. Missing measurements are marked Unknown rather than treated as safe.

## Route recommendation

Routes containing No Travel conditions are not eligible for recommendation. Routes with incomplete weather are also excluded. Remaining routes are ranked in this exact order:

1. Fewest Severe miles
2. Fewest High miles
3. Lowest distance-weighted average risk
4. Shortest travel time

Provider order is only used as the final deterministic tie-breaker.

Geoapify does not guarantee three alternatives in one response, so the backend requests several heavy-truck profiles: balanced, shortest distance and highway-light first, followed by fewer-maneuver and toll-conscious fallbacks. Duplicate geometry is rejected, and no more than five route calls are made for one analysis.

## Weather heatmap

The heatmap is built from hourly forecasts at route checkpoints. For the selected slider hour, the frontend converts risk levels into heat intensity and samples the actual route geometry so the heat stays on the trip corridor. Exact checkpoint markers remain on top for weather values, ETA and risk details.

This is an interpolated corridor view, not weather radar. That distinction is intentional because the application only requests weather at route checkpoints.

## Tests

Run the backend suite:

```bash
cd weather_truck_routing
../.venv/bin/python -m pytest
../.venv/bin/python manage.py check
```

Run frontend tests and create a production build:

```bash
cd frontend
npm run test
npm run build
```

The backend tests cover risk boundaries, cargo rules, checkpoint placement, arrival times, provider normalization, fallback routes, incomplete weather, No Travel handling, recommendation order and API responses.

## Deployment notes

The backend can run with Gunicorn using:

```bash
cd weather_truck_routing
gunicorn weather_truck_routing.wsgi:application
```

For production, set these environment variables on the backend host:

```text
DJANGO_SECRET_KEY=<a-long-random-value>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=<backend-hostname>
DJANGO_CORS_ALLOWED_ORIGINS=https://<frontend-hostname>
DJANGO_CSRF_TRUSTED_ORIGINS=https://<frontend-hostname>
GEOAPIFY_API_KEY=<your-key>
```

The frontend build command is `npm run build`, and the output directory is `frontend/dist`. Set `VITE_API_BASE_URL` to the public backend URL before building it.

No application data is stored, so SQLite is not part of the route-analysis flow. Django's standard migrations can still be run during deployment for the built-in framework applications.

## Data sources

- Routing and geocoding: Geoapify and OpenStreetMap contributors
- Weather forecasts: Open-Meteo
- Map tiles: OpenStreetMap contributors
