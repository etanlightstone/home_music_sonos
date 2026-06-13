Create a web app for playing local music files on my sonos speakers using a separate locally available sftp or ftp server and specific directory at that server as the source material. It should use a  file DB indexing system that explores the sftp / ftp server recursively to make search and navigation easy on the webserver. 

The webserver should have a main UI that presents a list of directories and music files to navigate just like I would if I were FTPing in myself (files in root folder, directories in root folder with breadcrumb system to navigate into folders etc) using whatever sorting seems natural (probably just default semi-alphabetical with folders first like google drive) and sorting by date of file. 

Only show files compatible with sonos playback (.mp3, .wav is there more?)

Each file should have 2 simple buttons, one for playback in the browser (this can literally just send the file over http directly to the browser, same way that's compatible with sonos python lib expects to play an mp3 directory from the web), the other button which is more prominent (use primary vs secondary button styles) plays the music file on sonos.

I'm not clear on how easy this is because I've only used the sonos python api / sdk for playing one file or basic stop/start but it would be great if the folders themselves also had a sonos playback button, this would play songs in order one at a time on the sonos player.

remember that since the files will be on a remote sftp (on same LAN) as far as the sonos python API is concerned we're giving a web address to the mp3 on THIS webserver, meaning you need to build (maybe part of indexing process?) URL that directly serves the mp3 from THIS web server over http that is basically a proxy reading from that sftp server.

There should be controls anchored to the top screen for basic playback controls (next/previous song, pause, resume, and label of current song playing).

just above the main music browser there should be a multifacet search, search string (make sure case sentitive doesn't matter) for file names or folder names, or restrict to just file names or restrict to just folder name results if I want to play that folder directly from the search results (I assume it can use the same panel or whatever as the main file browser while in search mode, consider a standard UX there).

I'm not sure how easy it is to read meta-data stored with the MP3 but if we can index that as well and include as part of the multi-facet search that would be great, however since our webserver will be accessing these files over sftp and not local to this webserver I'm not sure how easy that will be, so consider this last thing a bonus.. would it require literally downloading all songs just to read meta-data during indexing process? that would be many many gigs just to get the metadata right?

other than the main experience there should be a tab to do to the settings menu. These settings include the IP address of the sonos speaker to target (default can be 10.0.1.90). The sftp / ftp (simple dropdown toggle for what kind) server with username, password, and relative path to mp3 files. A button for re-indexing the sftp server (the main UI can have a nice empty state if we haven't indexed anything or no sftp configured yet). The button on the settings area for re-indexing can have an adjecent text saying when the last time indexing happened (potentially never happened). If indexing is happening (should ideally be a brackground task), the web UI should show that its in progress on both the main UI and the settings area if someone navigates there, a user can interrupt it but that effectively blanks out the db index. the file db is used for the web app settings as well of course, but separate from the index of music.

Tech stack should be a python FastAPI backend with simple javascript / html / css front-end that's darkthemed. no embedding huge amounts of js or front-end stuff in py files, but I also don't want a heavy reactJS front-end, you get the idea.

The webserver should have a simple app.sh script for running it.

