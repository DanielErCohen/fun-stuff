# Movie Night

A page for two people to choose what to watch. It deals one pick for tonight, keeps a To watch list and a Seen list, and takes a star rating from each of you.

Why I built it: I had a hard time choosing a film or series to watch. I preferred to back the choice with data and skip the endless scrolling through streaming services.

![Movie Night on a desktop screen: a dark marquee header, tabs for Tonight, To watch and Seen, and a ticket with tonight's pick.](docs/movie-night.png)

The marks, stars and notes in the picture are made up.

## Try it

Download the repository from its page on GitHub (**Code**, then **Download ZIP**), unzip it and open `movie-night/movie-night.html` in a browser. It runs on a made-up sample of films and series. Every button works. Your changes last until you close the tab.

## Make it yours

In the Claude desktop app, open the Code tab, start a new session (**+ New**) with the unzipped folder available to it, and paste this line:

> Read setup.md in the movie-night folder I downloaded and set up my Movie Night. Ask me the questions first and publish nothing until I confirm.

Claude asks you three things, one at a time: the first names of the two of you, your country and streaming services, and whether you start with an empty list or paste titles you already have. It reads back what it will build and publishes your page only after you say yes.

## What it needs

A Claude plan that can publish a private page with a database. I use the page this way with one other person. No other person has run this setup. Whether a second person can save changes from their own account is untested.

## What stays private

Your list, ratings and marks are saved in the database of your own private page. Claude writes your names and services into a copy of the file in your own folder, and the downloaded files stay as they are. The page loads its two fonts from Google Fonts, so opening it makes that one request.

## Licence

MIT, see [../LICENSE](../LICENSE).
