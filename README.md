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
