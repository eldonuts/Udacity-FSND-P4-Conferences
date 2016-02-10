#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from utils import getUserId

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import StringMessage
from models import Session
from models import SessionForm
from models import SessionForms
from models import Speaker

from settings import WEB_CLIENT_ID

__author__ = 'wesc+api@google.com (Wesley Chun)'

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_SPEAKERS_KEY = "FEATURED_SPEAKERS"

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    'city': 'Default City',
    'maxAttendees': 0,
    'seatsAvailable': 0,
    'topics': ['Default', 'Topic'],
}

OPERATORS = {
    'EQ': '=',
    'GT': '>',
    'GTEQ': '>=',
    'LT': '<',
    'LTEQ': '<=',
    'NE': '!='
}

FIELDS = {
    'CITY': 'city',
    'TOPIC': 'topics',
    'MONTH': 'month',
    'MAX_ATTENDEES': 'maxAttendees',
}

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST_BY_TYPE = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2),
)

SESSION_GET_REQUEST_BY_SPEAKER = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

WISHLIST_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    SessionKey=messages.StringField(1),
)

INTERESTED_POST_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    interestedTopic=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference',
               version='v1',
               allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
               scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copy_conference_to_form(self, conf, display_name=None):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if display_name:
            setattr(cf, 'organizerDisplayName', display_name)
        cf.check_initialized()
        return cf

    def _create_conference_object(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                              'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email'
                      )
        return request

    @ndb.transactional()
    def _update_conference_object(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copy_conference_to_form(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceForm, ConferenceForm,
                      path='conference',
                      http_method='POST',
                      name='createConference')
    def create_conference(self, request):
        """Create new conference."""
        return self._create_conference_object(request)

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='PUT',
                      name='updateConference')
    def update_conference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._update_conference_object(request)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='GET',
                      name='getConference')
    def get_conference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copy_conference_to_form(conf, getattr(prof, 'displayName'))

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getConferencesCreated',
                      http_method='POST',
                      name='getConferencesCreated')
    def get_conferences_created(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copy_conference_to_form(conf, getattr(prof, 'displayName')) for conf in confs]
        )

    def _get_query(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._format_filters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _format_filters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return inequality_field, formatted_filters

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def query_conferences(self, request):
        """Query for conferences."""
        conferences = self._get_query(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copy_conference_to_form(conf, names[conf.organizerUserId]) for conf in conferences]
        )


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copy_profile_to_form(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _get_profile_from_user(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key=p_key,
                displayName=user.nickname(),
                mainEmail=user.email(),
                teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile

    def _do_profile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._get_profile_from_user()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
            prof.put()
        # return ProfileForm
        return self._copy_profile_to_form(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile',
                      http_method='GET',
                      name='getProfile')
    def get_profile(self, request):
        """Return user profile."""
        return self._do_profile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile',
                      http_method='POST',
                      name='saveProfile')
    def save_profile(self, request):
        """Update & return user profile."""
        return self._do_profile(request)

# - - - Profile: Interested Topics - - - - - - - - - - - - -

    def _interested_topic(self, request, add=True):
        retval = None
        prof = self._get_profile_from_user()  # get user Profile

        request_topic = request.interestedTopic
        interested = prof.interestedTopics

        # add
        if add:
            # check if user already registered otherwise add
            if request_topic in interested:
                raise ConflictException(
                    "You already have this in your interested topics")

            # add to wish list
            prof.interestedTopics.append(request_topic)
            retval = True

        # remove
        else:
            # check if user already registered
            if request_topic in interested:
                prof.interestedTopics.remove(request_topic)
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        return BooleanMessage(data=retval)

    @endpoints.method(INTERESTED_POST_REQUEST, BooleanMessage,
                      path='topicFav/add',
                      http_method='POST',
                      name='addTopicInterested')
    def add_topic_interested(self, request):
        """Add topic to current users interested topics"""
        return self._interested_topic(request)

    @endpoints.method(INTERESTED_POST_REQUEST, BooleanMessage,
                      path='topicFav/delete',
                      http_method='POST',
                      name='deleteTopicInterested')
    def delete_topic_interested(self, request):
        """Remove topic from users interested topics"""
        return self._interested_topic(request, add=False)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getConferencesWithTopics',
                      http_method='POST',
                      name='getConferencesWithTopics')
    def get_conferences_with_topics(self, request):
        """Return conferences that match current users interests."""
        # make sure user is authenticated
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        user_id = getUserId(user)
        prof = ndb.Key(Profile, user_id).get()

        confs = Conference.query(Conference.topics.IN(prof.interestedTopics))

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copy_conference_to_form(conf) for conf in confs]
        )


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conference_registration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._get_profile_from_user() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET',
                      name='getConferencesToAttend')
    def get_conferences_to_attend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._get_profile_from_user() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copy_conference_to_form(conf, names[conf.organizerUserId])\
                                      for conf in conferences]
        )

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST',
                      name='registerForConference')
    def register_for_conference(self, request):
        """Register user for selected conference."""
        return self._conference_registration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='DELETE',
                      name='unregisterFromConference')
    def unregister_from_conference(self, request):
        """Unregister user for selected conference."""
        return self._conference_registration(request, reg=False)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cache_announcement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET',
                      name='getAnnouncement')
    def get_announcement(self, request):
        """Return Announcement from memcache."""
        get_announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if get_announcement:
            announcement = get_announcement
        else:
            announcement = ""
        return StringMessage(data=announcement)


# - - - Sessions - - - - - - - - - - - - - - - - - - - -

    def _copy_session_to_form(self, session):
        form = SessionForm()
        for field in form.all_fields():
            if hasattr(session, field.name):
                # convert Time and date types to string; just copy others
                if field.name.endswith('Time') or field.name.startswith('date'):
                    setattr(form, field.name, str(getattr(session, field.name)))
                else:
                    setattr(form, field.name, getattr(session, field.name))
            elif field.name == "websafeKey":
                setattr(form, field.name, session.key.urlsafe())
        form.check_initialized()
        return form

    def _create_session_object(self, request):
        """Create the session object and put into datastore"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        conference = c_key.get()

        # Do checks
        if user_id != conference.organizerUserId:
            raise endpoints.BadRequestException("Current user not authorised to add session for this conference")
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")
        if not request.durationTime:
            raise endpoints.BadRequestException("Session 'durationTime' field required")
        if not request.date:
            raise endpoints.BadRequestException("Session 'date' field required")
        if not request.startTime:
            raise endpoints.BadRequestException("Session 'startTime' field required")

        # copy request into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeConferenceKey']
        del data['websafeKey']



        s_id = Session.allocate_ids(size=1, parent=c_key)
        s_key = ndb.Key(Session, s_id[0], parent=c_key)

        data['key'] = s_key

        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], '%Y-%m-%d').date()

        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'], '%H:%M').time()

        if data['durationTime']:
            data['durationTime'] = datetime.strptime(data['durationTime'], '%H:%M').time()

        # create Session
        session = Session(**data).put()

        # get the newly created Session so we can pass back the websafeKey
        new_session = session.get()

        if data['speaker']:
            try:
                speaker = Speaker.query(Speaker.name == data['speaker']).fetch()[0]
            except:
                speaker_id = Speaker.allocate_ids(size=1, parent=s_key)
                speaker_key = ndb.Key(Speaker, speaker_id[0], parent=s_key)
                new_speaker = Speaker(name=data['speaker'], key=speaker_key)
                speaker_key = new_speaker.put()
                speaker = speaker_key.get()

            speaker.sessions.append(new_session.name)
            speaker.put()

            # Add 'Get Featured Speaker' task to queue
            taskqueue.add(url='/tasks/set_featured_speakers', params={'speaker_key': speaker.key.urlsafe()})

        return self._copy_session_to_form(new_session)

    @endpoints.method(SESSION_POST_REQUEST, SessionForm,
                      path='sessions/create',
                      http_method='POST',
                      name='createSession')
    def create_session(self, request):
        """Create a session"""
        return self._create_session_object(request)

    def _get_sessions(self, websafeConferenceKey):
        """Return formatted query from the submitted filters."""
        q = Session.query(ancestor=ndb.Key(Conference, websafeConferenceKey))
        return q

    def _get_sessions_by_type(self, websafeConferenceKey, typeOfSession):
        q = Session.query(ancestor=ndb.Key(Conference, websafeConferenceKey))
        q = q.filter(Session.typeOfSession == typeOfSession)
        return q

    def _get_sessions_by_speaker(self, speaker):
        q = Session.query(Session.speaker == speaker)
        return q

    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
                      path='sessions',
                      http_method='GET',
                      name='getConferenceSessions')
    def get_conference_sessions(self, request):
        """Get sessions."""
        sessions = self._get_sessions(request.websafeConferenceKey)

        return SessionForms(
            items=[self._copy_session_to_form(session) for session in sessions]
        )

    @endpoints.method(SESSION_GET_REQUEST_BY_TYPE, SessionForms,
                      path='session/type',
                      http_method='GET',
                      name='getConferenceSessionsByType')
    def get_conference_sessions_by_type(self, request):
        """Get sessions by conference and type."""
        sessions = self._get_sessions_by_type(request.websafeConferenceKey, request.typeOfSession)
        return SessionForms(
            items=[self._copy_session_to_form(session) for session in sessions]
        )

    @endpoints.method(SESSION_GET_REQUEST_BY_SPEAKER, SessionForms,
                      path='sessions/speaker',
                      http_method='GET',
                      name='getSessionsBySpeaker')
    def get_sessions_by_speaker(self, request):
        """Get sessions by speaker."""
        sessions = self._get_sessions_by_speaker(request.speaker)
        return SessionForms(
            items=[self._copy_session_to_form(session) for session in sessions]
        )

    def _session_wishlist(self, request, add=True):
        retval = None
        prof = self._get_profile_from_user()  # get user Profile

        # check if session exists given SessionKey
        sk = request.SessionKey
        session = ndb.Key(urlsafe=sk).get()
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % sk)
        # add
        if add:
            # check if user already registered otherwise add
            if sk in prof.sessionsInWishlist:
                raise ConflictException(
                    "You have already registered for this session")
            # add to wishlist
            prof.sessionsInWishlist.append(sk)
            retval = True

        # remove
        else:
            # check if user already registered
            if sk in prof.sessionsInWishlist:
                prof.sessionsInWishlist.remove(sk)
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        return BooleanMessage(data=retval)

    @endpoints.method(WISHLIST_GET_REQUEST, BooleanMessage,
                      path='wishlist/add',
                      http_method='POST',
                      name='addSessionToWishlist')
    def add_session_to_wishlist(self, request):
        """Add session to current users wishlist"""
        return self._session_wishlist(request)
    
    @endpoints.method(WISHLIST_GET_REQUEST, BooleanMessage,
                      path='wishlist/delete',
                      http_method='POST',
                      name='deleteSessionInWishlist')
    def delete_session_in_wishlist(self, request):
        """Remove session to current users wishlist"""
        return self._session_wishlist(request, add=False)
    
    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='wishlist',
                      http_method='GET',
                      name='getSessionsInWishlist')
    def get_sessions_in_wishlist(self, request):
        """Return sessions in users wishlist."""
        prof = self._get_profile_from_user() # get user Profile
        sessions_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.sessionsInWishlist]
        sessions = ndb.get_multi(sessions_keys)

        # return set of ConferenceForm objects per Conference
        return SessionForms(items=[self._copy_session_to_form(session) for session in sessions])

    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='finishedSessions',
                      http_method='GET',
                      name='getFinishedSessions')
    def get_finished_sessions(self, request):
        """Return sessions that have already finished"""
        sessions = Session.query(Session.endDateTime < datetime.now())
        return SessionForms(items=[self._copy_session_to_form(session) for session in sessions])

    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='NonWorkshopsBefore7',
                      http_method='GET',
                      name='getNonWorkshopsBefore7')
    def get_non_workshops_before_7(self, request):
        """Return sessions that aren't workshops and finish before 7"""
        sessions = Session.query(Session.finishBeforeSeven == True)
        sessions = sessions.filter(Session.typeOfSession != ('workshop' or 'Workshop'))
        return SessionForms(items=[self._copy_session_to_form(session) for session in sessions])


# - - - Featured Speakers - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cache_featured_speaker(speaker_key):
        """Create featured speaker & assign to memcache; used by
        memcache cron job.
        """
        speaker = ndb.Key(urlsafe=speaker_key).get()

        if speaker:
            if len(speaker.sessions) >= 2:
                featured = '%s %s %s %s' % (
                    'Featured Speaker:',
                    speaker.name, '| Sessions:',
                    ', '.join(speaker.sessions))
                memcache.set(MEMCACHE_FEATURED_SPEAKERS_KEY, featured)
            else:
                # delete the memcache speakers entry
                featured = ""
                memcache.delete(MEMCACHE_FEATURED_SPEAKERS_KEY)

        return featured

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/featured_speaker/get',
                      http_method='GET',
                      name='getFeaturedSpeaker')
    def get_announcement(self, request):
        """Return Announcement from memcache."""
        get_speaker = memcache.get(MEMCACHE_FEATURED_SPEAKERS_KEY)
        if get_speaker:
            speaker = get_speaker
        else:
            speaker = ""
        return StringMessage(data=speaker)


api = endpoints.api_server([ConferenceApi])  # register API
