# About this program

This program captures periodic snapshots of M3U8 streams and saves them as jpg file. Additionally, if the process fails after x attempts, there is an option to be notified via Webhook.

# How to use

### Clone the repo

Use `git clone https://github.com/AlexanderBarthe/WebcamSnapper` in the desired directory.


### Edit the .env file

In the .env file replace `YOUR_M3U8_SOURCE_URL` with the URL of the M3U8 stream. This is mandatory.
You can also add your webhook url and payload and edit some other variables. Note, that the quality of the images get better, the smaller the `QUALITY` value is.


### Startup

If you haven't installed Docker and Docker Compose on your system yet, you can find a guide [here](https://docs.docker.com/engine/install/).

In the directory run `docker compose up -d --build`.

To stop run `docker compose down`.

