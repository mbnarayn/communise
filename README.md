# Local Directory Website

A simple local directory app for shops and amenities. Users can browse listings and add new ones through a clean web form.

## Features
- Clean, modern directory layout
- Local shop and amenity listings
- Add-your-own listing form
- Data stored in a simple JSON file so it works without a database
- Ready to deploy to Azure App Service using Python 3.14

## Run locally

By default, the app keeps data in a local JSON file so it works without extra setup.

```bash
python app.py
```

Then open:

```text
http://localhost:8000
```

### Listing logos

Logo uploads are limited to PNG, JPEG, and WebP files up to 2 MB. During local
development, uploaded logos are stored in `static/uploads/logos/` and the
listing keeps the corresponding static URL.

To use Azure Blob Storage instead, set the storage account URL and optional
container name before starting the app:

```bash
export AZURE_STORAGE_ACCOUNT_URL=https://<storage-account>.blob.core.windows.net
export AZURE_STORAGE_CONTAINER=listing-logos
```

When `AZURE_STORAGE_ACCOUNT_URL` is set, the app uses Azure managed identity
authentication and uploads logos to Blob Storage. The App Service identity
needs the `Storage Blob Data Contributor` role on the storage account, and the
container must already exist.

For local managed-identity-style authentication, sign in with:

```bash
az login
```

Uploaded logos are stored at `listing-logos/<listing-id>/logo.<extension>`.

For local testing or environments without managed identity, you can provide a
storage account key instead:

```bash
export AZURE_STORAGE_ACCOUNT_KEY=<storage-account-key>
```

When the key is present, it takes precedence over managed identity. Store it
in a secret manager and rotate it regularly; do not commit it to source control.

## Use Azure Cosmos DB

To switch the app to Azure Cosmos DB, add the following environment variables before running the app:

```bash
set COSMOS_ENDPOINT=https://<your-account>.documents.azure.com:443/
set COSMOS_KEY=<your-primary-key>
set COSMOS_DATABASE=local-directory
set COSMOS_CONTAINER=listings
```

Then run:

```bash
python app.py
```

The app will automatically use Cosmos DB instead of the JSON file when those values are present.

## Upcoming events

Visitors can browse upcoming events at `/events`, search by event name, description, venue,
community or date, filter by community, and submit an event at `/events/add`. Clear removes
the search text while keeping the selected community.
Event community choices include Milton Keynes, Buckingham, Woking, and Other.
Submissions are visible only after an admin approves them under `/admin` (Review Events).
Visitors can request edits or deletion from an approved event's detail page. The current
event stays published unchanged until an admin approves the request; rejecting it keeps
the current event. Admins can also request removal of published events for review.
Event tiles list the nearest dates first in UK format with their times, event name,
description, community, View Details link and a view count. Opening event details counts
once per browser session for that event, even when it has multiple dates. The detail page shows the venue, all
upcoming dates and any registration or ticket link.
Going and Not Going buttons appear on event tiles and details. Each browser session can
record one response per event and can switch its response; all dates for that event share
the same counts.
Events have a name, description, community, required Address / Venue, and one or more dates,
each with its own start and end time. An optional event details, registration, or tickets URL
can link visitors to more information. Past dates are not shown publicly, even
when other dates for the same event are upcoming. Locally, events are saved separately
from listings in `data/events.json`.

When Cosmos DB is configured, events use a separate container (default `events`) in the same
database, partitioned by `/community`. The app creates the container if it does not exist. To
use another container name, set `COSMOS_EVENTS_CONTAINER` before running the app. If creating
the container manually, its partition key must be `/community`. The configured Cosmos account
key must have permission to create the container and read/write events.

## Deploy to Azure App Service

1. Create a Linux Web App using Python 3.14:

```bash
az webapp create \
  --resource-group <your-resource-group> \
  --plan <your-app-service-plan> \
  --name <your-webapp-name> \
  --runtime "PYTHON|3.14"
```

2. Configure deployment from your local folder or GitHub.
3. Set the startup command:

```bash
gunicorn --bind=0.0.0.0 --timeout 600 app:app
```

4. Add the Cosmos environment variables in the Azure App Service configuration or via `az webapp config appsettings set`.
5. Deploy the project contents and verify the site loads.

## Project structure

- `app.py` - Flask application
- `templates/` - HTML pages
- `static/` - CSS styles
- `data/listings.json` - saved listings
- `requirements.txt` - Python dependencies
