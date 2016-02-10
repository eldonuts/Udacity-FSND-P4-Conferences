App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool

### Project Notes

## Task 1
The first step was deciding how to structure the sessions. This was easy, as I knew the best way to do this was to define sessions as a new Kind. Most of my design was based around the Conferences Kind, taking inspiration where needed. I also decided that the speaker should have its own Kind, as it will be much nicer to work with in the later Tasks (I actually decided this later on).

I also added some Computer Properties that are updated when each session is updated so I could get extra info such as the end time, and if they finished before 7 or not.

## Task 2
Wishlist methods were added as required.

## Task 3
My two additional queries were:
- getFinishedSessions: This retrieved session that has already happened (UTC time)
- getConferencesWithTopics (with additional support methods addTopicInterested and deleteTopicInterested): The methods were used to add interested topics to a users profile, and then could be used to tell what Conferences contained any of those topics.

As for the query related problem (sessions after 7 that weren't workshops), the main problem I saw was there was no way to know when the sessions were going to finish. To solve this, I created a Computed Property (mentioned in Task 1 notes) that worked out if the conferenced finished after 7. Then I simply made a new method that used this property and filtered out workshops (getNonWorkshopsBefore7).

## Task 4
I implemented this as per the project requirements.
