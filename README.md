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
