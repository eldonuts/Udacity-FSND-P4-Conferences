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

## Project Notes

### Task 1
####Design Choices (Response)
I decided that to efficiently structure the session functionality, Kinds needed to be created for Session and Speaker. The Session has a relationship with each Conferernce. For the relationship between session and speaker, I chose to allow user string input for the speaker so that they didn't have to create a speaker entity first, they could just type them in and the application would create the entity for them. This does require each speaker to have a different name. 

As for the added Session model object, most properties were simple strings but the following were also included:
-durationMinutes: IntergerProperty used so it was easier to add to the start time to get the end time.
-date: DateProperty used to make sure the data in a formate that could be combined with startTime easily and used to compare.
-startTime: TimeProperty used to make sure the data in a formate that could be combined with date easily and used to compare.
-endDateTime: ComputedProperty used rather than builtin Python @property so that whenever the entity is changed this will update.
-finishBeforeSeven: Same as above, but returns a boolean value so we can easily tell if the session finishes before 7pm.

### Task 3
####Additional Queries
My two additional queries were:
- getFinishedSessions: This retrieved session that has already happened (UTC time)
- getConferencesWithTopics (with additional support methods addTopicInterested and deleteTopicInterested): The methods were used to add interested topics to a users profile, and then could be used to tell what Conferences contained any of those topics.

####Query Problem
The main problem I saw was there was no way to know when the sessions were going to finish. To solve this, I created a Computed Property (mentioned in Task 1 notes) that worked out if the conferenced finished after 7. Additionally, there was no start datetime property, so the date and start time properties needed to be combined before the duration time could be added. Then I simply made a new method that used the calculated property and filtered out workshops (getNonWorkshopsBefore7)
