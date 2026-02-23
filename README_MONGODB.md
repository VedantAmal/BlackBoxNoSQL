# MongoDB Atlas Setup Guide

This project has been migrated to use MongoDB. You can run MongoDB locally or use MongoDB Atlas (Cloud).

## Using MongoDB Atlas

1.  **Create an Account**: Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) and create an account.
2.  **Create a Cluster**: Create a new cluster (the free tier is sufficient for development).
3.  **Create a Database User**:
    *   Go to "Database Access".
    *   Add a new database user with a username and password.
    *   Grant "Read and write to any database" privileges.
4.  **Network Access**:
    *   Go to "Network Access".
    *   Add IP Address.
    *   Select "Allow Access from Anywhere" (0.0.0.0/0) for development, or add your specific IP.
5.  **Get Connection String**:
    *   Go to "Database" -> "Connect".
    *   Select "Drivers".
    *   Copy the connection string (e.g., `mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority`).

## Configuration

You can configure the application to use MongoDB Atlas by setting the `MONGODB_URI` environment variable.

### Option 1: `.env` file (Recommended for local dev)

Create or update your `.env` file in the project root:

```bash
MONGODB_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/ctf_platform?retryWrites=true&w=majority
```

Replace `<username>` and `<password>` with the credentials you created in step 3. Replace `ctf_platform` with your desired database name.

### Option 2: Environment Variables

Set the environment variable directly in your shell or deployment platform:

**Linux/Mac:**
```bash
export MONGODB_URI="mongodb+srv://<username>:<password>@cluster0.mongodb.net/ctf_platform?retryWrites=true&w=majority"
```

**Windows (PowerShell):**
```powershell
$env:MONGODB_URI = "mongodb+srv://<username>:<password>@cluster0.mongodb.net/ctf_platform?retryWrites=true&w=majority"
```

## Local MongoDB

If you prefer to run MongoDB locally, ensure you have MongoDB installed and running. The application defaults to `localhost:27017` if `MONGODB_URI` is not set.

You can also use Docker:
```bash
docker run -d -p 27017:27017 --name mongodb mongo:latest
```
