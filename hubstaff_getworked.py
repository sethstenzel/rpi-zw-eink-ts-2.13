import requests
import json
import datetime
import inspect
import logging
import time

logging.basicConfig(
    filename='logs.log',
    filemode='a',
    format='%(asctime)s %(levelname)s %(message)s',
    level=logging.INFO   
    )
logging.getLogger().addHandler(logging.StreamHandler())


def load_tokens_from_file() -> tuple:
    """Loads the refresh token from refresh_token.json which is expected to
    to be in the same directory.

    Returns:
        tuple: access_token, access_expiry, refresh_token
    """
    logging.debug("loading from refresh_token.json")
    with open('refresh_token.json') as json_file:
        token_data = json.load(json_file)
    return token_data["access_token"], token_data["access_expiry"], token_data["refresh_token"]

def get_token_endpoint(hubstaff_openid_configuration_url) -> str:
    """Hubstaff uses OpenID which has a standard endpoint which returns current details
    relating to authentication, refresh, and other URL's for authentication. When using
    a user token instead of OAuth 2 + OpenID the generated token is considered a refresh
    token. get an access token and a new refresh token the current endpoint for these
    operations must be fetched dynamically.

    Returns:
        str: token_endpoint
    """    
    logging.debug("getting token endpoint")
    open_id_configuration_details = requests.get(hubstaff_openid_configuration_url).json()

    return open_id_configuration_details["token_endpoint"]

def get_access_token_access_expiry_and_new_refresh_token(refresh_token, token_endpoint) -> tuple:
    """When accessing hubstaff with a user token, an access token must be requested.
    The request reponse will also contain a new refresh_token which will need to be saved
    for future requests.

    Returns:
        tuple: access_token, new_refresh_token
    """
    logging.debug("getting new tokens")
    data = {
        'grant_type' : 'refresh_token',
        'refresh_token': f'{refresh_token}'
    }
    response = requests.post(f'{token_endpoint}', data=data)

    access_token = response.json()['access_token']
    new_refresh_token = response.json()['refresh_token']

    expires_in = int(response.json()['expires_in'])
    access_expiry = (datetime.datetime.now() + datetime.timedelta(seconds=expires_in)).strftime("%Y-%m-%d %I:%M%p")
    
    return access_token, access_expiry, new_refresh_token

def save_tokens_to_file(access_token, access_expiry, new_refresh_token):
    logging.debug("saving tokens to refresh_token.json")
    with open("refresh_token.json", "w") as json_file:
        json.dump({"access_token":access_token, "access_expiry":access_expiry, "refresh_token":new_refresh_token}, json_file)


def get_user_id(hubstaff_base_api_url, access_token) -> str:
    logging.debug("getting user_id")
    request_headers = {"Authorization" : f"Bearer {access_token}"}
    user_details_request = requests.get(f'{hubstaff_base_api_url}/v2/users/me', headers=request_headers)
    return user_details_request.json()["user"]["id"]


def get_organization_id(hubstaff_base_api_url, access_token):
    logging.debug("getting organization_id")
    request_headers = {"Authorization" : f"Bearer {access_token}"}
    organizations = requests.get(f'{hubstaff_base_api_url}/v2/organizations', headers=request_headers)

    for org in organizations.json()["organizations"]:
        if "NXLog" in org["name"]:
            organization_id = org["id"]

    return organization_id


def get_billable_activity(
    hubstaff_base_api_url,
    access_token,
    user_id,
    organization_id
) -> int:

    logging.debug("getting billable_activity")

    start_date = (datetime.datetime.now() + datetime.timedelta(hours=7)).strftime("%Y-%m-%d")
    end_date = (datetime.datetime.now() + datetime.timedelta(hours=7)).strftime("%Y-%m-%d")  

    request_headers = {"Authorization" : f"Bearer {access_token}"}

    activities_url = inspect.cleandoc(f'''
        {hubstaff_base_api_url}/v2/organizations/{organization_id}/activities/daily?
        date[start]={start_date}&
        date[stop]={end_date}&
        user_ids={user_id}&
        include=users'''
    ).replace("\n","")
    activities_request = requests.get(f'{activities_url}', headers=request_headers)
    activities = activities_request.json()['daily_activities']

    activity_time_in_seconds = 0
    for day in activities:
        activity_time_in_seconds += day['billable']

    return activity_time_in_seconds


def get_time_remaining(desired_worked_hours_per_day, billable_activity_in_seconds) -> int:
    desired_worked_seconds_per_day = desired_worked_hours_per_day * 60 * 60
    work_time_remaining = desired_worked_seconds_per_day - billable_activity_in_seconds

    if work_time_remaining < 0:
        work_time_remaining = 0

    return work_time_remaining
       
def format_time_from_seconds(seconds):
    hours = int(seconds/3600)
    if hours > 0:
        seconds = seconds - hours * 3600
        
    minutes = int(seconds/60)
    if minutes > 0:
        seconds = seconds - minutes * 60
    seconds = int(seconds)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def main():
    hubstaff_openid_configuration_url = "https://account.hubstaff.com/.well-known/openid-configuration"
    hubstaff_base_api_url = "https://api.hubstaff.com/"
    desired_worked_hours_per_day = 8.5

    access_token, access_expiry, refresh_token = load_tokens_from_file()

    while True:
        try:        
            if datetime.datetime.now() + datetime.timedelta(minutes=5) > datetime.datetime.strptime(access_expiry, "%Y-%m-%d %I:%M%p"):
                logging.info("The access_token has expired(or is near to). Getting new tokens.")
                token_endpoint = get_token_endpoint(hubstaff_openid_configuration_url)
                access_token, access_expiry, new_refresh_token = get_access_token_access_expiry_and_new_refresh_token(refresh_token, token_endpoint)
                save_tokens_to_file(access_token, access_expiry, new_refresh_token)

            user_id = get_user_id(hubstaff_base_api_url, access_token)
            organization_id = get_organization_id(hubstaff_base_api_url, access_token)
            billable_activity_in_seconds = get_billable_activity(hubstaff_base_api_url, access_token, user_id, organization_id)

            work_time_remaining = get_time_remaining(desired_worked_hours_per_day, billable_activity_in_seconds)

            print(f"Worked Today:    {format_time_from_seconds(billable_activity_in_seconds)}")
            if work_time_remaining > 0:
                print(f"Time Remaining:  {format_time_from_seconds(work_time_remaining)}")
            else:
                print(f"Time Remaining:  None")

        except requests.exceptions.RequestException as e:
            logging.error(f"RequestException: {e}")
        logging.debug("Sleeping for 60 seconds...")
        time.sleep(60)
    
      
if __name__ == "__main__":
    main()





