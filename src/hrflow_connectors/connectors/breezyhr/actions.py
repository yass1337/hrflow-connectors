from typing import Iterator, Dict, Any, Optional
from pydantic import Field
import requests

from ...core.error import PullError, PushError
from ...core.action import PullJobsBaseAction, PushProfileBaseAction
from ...core.auth import OAuth2EmailPasswordBody
from ...utils.logger import get_logger
from ...utils.clean_text import remove_html_tags
from ...utils.hrflow import generate_workflow_response
from ...utils.datetime_converter import from_str_to_datetime
from ...utils.schemas import HrflowJob, HrflowProfile
from .schemas import BreezyJobModel, BreezyProfileModel

logger = get_logger()


class PullJobsAction(PullJobsBaseAction):

    auth: OAuth2EmailPasswordBody
    company_id: Optional[str] = Field(
        None,
        description="ID of company to pull jobs from in Breezy HR database associated with the authenticated user",
    )
    company_name: Optional[str] = Field(
        None, description="the company associated with the authenticated user"
    )

    def pull(self) -> Iterator[BreezyJobModel]:
        """
        Pull jobs from a Taleez jobs owner endpoint
        Returns list of all jobs that have been pulled
        """

        def get_company_id() -> str:
            """
            Get the company id associated with the authenticated user company
            """
            if self.company_id is not None:
                return self.company_id
            else:
                get_company_id_request = requests.Request()
                get_company_id_request.method = "GET"
                get_company_id_request.url = "https://api.breezy.hr/v3/companies"
                get_company_id_request.auth = self.auth
                prepared_request = get_company_id_request.prepare()
                response = session.send(prepared_request)
                if not response.ok:
                    raise PullError(response, message="Couldn't get company id")
                company_list = response.json()
                logger.debug("Retrieving company id")
                for company in company_list:
                    if company["name"] == self.company_name:
                        return company["_id"]

        # Prepare request
        session = requests.Session()
        pull_jobs_request = requests.Request()
        pull_jobs_request.method = "GET"
        pull_jobs_request.url = (
            f"https://api.breezy.hr/v3/company/{get_company_id()}/positions?"
        )
        pull_jobs_request.auth = self.auth
        prepared_request = pull_jobs_request.prepare()

        # Send request
        response = session.send(prepared_request)

        if not response.ok:
            raise PullError(response, message="Failed to get jobs from this endpoint")
        job_json_list = response.json()
        job_obj_iter = map(BreezyJobModel.parse_obj, job_json_list)

        return job_obj_iter

    def format(self, data: BreezyJobModel) -> HrflowJob:
        """
        Format a Breezy Hr job object into a hrflow job object

        Returns:
            HrflowJob: a job object in the hrflow job format
        """
        data = data.dict()
        print(data)
        job = dict()
        # Basic information
        job["name"] = data.get("name")
        logger.info(job["name"])
        job["reference"] = data.get("friendly_id")
        logger.info(job["reference"])
        job["summary"] = None

        # Location
        location = data.get("location")
        country = location.get("country")
        country_name = country.get("name")
        city = location.get("city")
        address = location.get("name")
        geojson = dict(country=country_name, city=city)

        job["location"] = dict(text=address, geojson=geojson, lat=None, lng=None)

        # Sections
        description = remove_html_tags(data.get("description"))
        cleaned_description = description.replace("&nbsp;", " ")
        job["sections"] = [
            dict(
                name="breezy_hr_description",
                title="Breezy_hr_description",
                description=cleaned_description,
            )
        ]
        # tags
        job["tags"] = []

        def create_tag(field_name: str):
            tag_name = "breezy_hr_{}".format(field_name)
            tag_value = data.get(field_name)

            if isinstance(tag_value, dict):
                tag_name_value = tag_value.get("name")
                tag = dict(name=tag_name, value=tag_name_value)
                job["tags"].append(tag)
            if isinstance(tag_value, str):
                tag = dict(name=tag_name, value=tag_value)
                job["tags"].append(tag)

        create_tag("type")
        create_tag("experience")
        create_tag("education")
        create_tag("department")
        create_tag("requisition_id")
        create_tag("category")
        create_tag("candidate_type")
        is_remote = dict(name="breezy_hr_remote", value=location.get("is_remote"))
        job["tags"].append(is_remote)

        job["created_at"] = data.get("creation_date")
        job["updated_at"] = data.get("updated_date")
        job_obj = HrflowJob.parse_obj(job)

        return job_obj


class PushProfileAction(PushProfileBaseAction):

    auth: OAuth2EmailPasswordBody
    company_id: Optional[str] = Field(
        None,
        description="ID of company to pull jobs from in Breezy HR database associated with the authenticated user",
    )
    company_name: Optional[str] = Field(
        None, description="the company associated with the authenticated user"
    )
    position_id: str = Field(
        ..., description="Id of the position to create a new candidate for"
    )
    origin: Optional[str] = Field(
        "sourced",
        description="will indicate in Breezy if the candidate should be marked as sourced or applied",
    )
    cover_letter: Optional[str] = None

    def format(self, data: HrflowProfile) -> BreezyProfileModel:
        """
        Format a Hrflow profile object into a breezy hr profile object

        Args:
            data (HrflowProfile): Hrflow Profile to format

        Returns:
            BreezyProfileModel: a BreezyHr formatted profile object
        """

        profile = dict()
        data = data.dict()
        info = data.get("info")
        profile["name"] = info.get("full_name")
        profile["address"] = info.get("location").get("text")
        profile["email_address"] = info.get("email")
        profile["phone_number"] = info.get("phone")
        profile["summary"] = info.get("summary")
        if self.origin is not None:
            profile["origin"] = self.origin

        profile["work_history"] = []

        def format_experiences():

            experiences = data.get("experiences")
            for experience in experiences:
                format_experience = dict()
                if experience["company"] not in ["", None]:
                    format_experience["company_name"] = experience["company"]
                else:
                    format_experience["company_name"] = "Undefined"
                format_experience["title"] = experience["title"]
                format_experience["summary"] = experience["description"]
                if experience["date_start"] is not None:
                    date_iso = from_str_to_datetime((experience["date_start"]))
                    format_experience["start_year"] = date_iso.year
                    format_experience["start_month"] = date_iso.month
                if experience["date_end"] is not None:
                    date_end_iso = from_str_to_datetime((experience["date_end"]))
                    format_experience["end_year"] = date_end_iso.year
                    format_experience["end_month"] = date_end_iso.month

                profile["work_history"].append(format_experience)

        format_experiences()

        profile["education"] = []

        def format_educations():
            educations = data.get("educations")
            for education in educations:
                format_education = dict()
                if education["school"] == "":
                    education["school"] = "Undefined"
                format_education["school_name"] = education["school"]
                format_education["field_of_study"] = education["title"]
                if education["date_start"] is not None:
                    date_iso = from_str_to_datetime((education["date_start"]))
                    format_education["start_year"] = date_iso.year
                if education["date_end"] is not None:
                    date_end_iso = from_str_to_datetime((education["date_end"]))
                    format_education["end_year"] = date_end_iso.year
                profile["education"].append(format_education)

        format_educations()

        profile["social_profiles"] = []

        def format_urls() -> None:
            """
            format_urls, add links and websites to Taleez profile Social links
            """
            urls = info.get("urls")
            if isinstance(urls, list):
                for url in urls:
                    type = url.get("type")
                    link = url.get("url")
                    if isinstance(link, str):
                        profile["social_profiles"][type] = link
            attachments = info.get("attachments")
            if isinstance(attachments, list):
                for attachment in attachments:
                    file_name = attachment.get("file_name")
                    public_url = attachment.get("public_url")
                    if isinstance(public_url, str):
                        profile["social_profiles"][file_name] = public_url

        format_urls()
        if self.cover_letter is not None:
            profile["cover_letter"] = self.cover_letter

        # add profile skills to tags
        profile["tags"] = []
        skills = data.get("skills")
        if isinstance(skills, list):
            for skill in skills:
                if isinstance(skill, dict):
                    profile["tags"].append(skill["name"])

        profile_obj = BreezyProfileModel.parse_obj(profile)
        return profile_obj

    def push(self, data: BreezyProfileModel) -> None:
        """
        Push a Hrflow profile object to a BreezyHr candidate pool for a position

        Args:
            data (BreezyProfileModel): profile to push
        """
        profile = next(data)
        auth = self.auth
        session = requests.Session()

        def send_request(
            error_message: str,
            method: str,
            url: str,
            json: Optional[Dict[str, Any]] = None,
        ) -> requests.Response:
            """
            Send a HTTPS request to the specified url using the specified paramters

            Args:
                error_message (str): message to be displayed when a PushError is raised
                method (str): request method: "GET", "PUT", "POST"...
                url (str): url endpoint to receive the request
                json (optional): data to be sent to the endpoint. Defaults to None.
                return_response (optional): In case we want to the function to return the response. Defaults to None.

            Returns:
                response (requests.Response)
            """
            request = requests.Request()
            request.method = method
            request.url = url
            request.auth = auth
            if json is not None:
                request.json = json
            prepared_request = request.prepare()
            response = session.send(prepared_request)
            if not response.ok:
                raise PushError(response, message=error_message)
            return response

        # if the user doesn't specify a company id, we send a request to retrieve it using company_name
        if self.company_id is None:
            get_company_id_response = send_request(
                method="GET",
                url="https://api.breezy.hr/v3/companies",
                error_message="Couldn't get company id",
            )
            company_list = get_company_id_response.json()
            for company in company_list:
                if company["name"] == self.company_name:
                    self.company_id = company["_id"]

        # a request to verify if the candidate profile already exist
        get_candidate_url = f"https://api.breezy.hr/v3/company/{self.company_id}/candidates/search?email_address={profile.email_address}"
        get_candidate_response = send_request(
            method="GET",
            url=get_candidate_url,
            error_message="Couldn't get candidate",
        )
        candidate_list = get_candidate_response.json()
        candidate = None
        if candidate_list != []:
            candidate = candidate_list[0]

        # In case the candidate exists we retrieve his id to update his profile with a "PUT" request
        if candidate is not None:
            candidate_id = candidate["_id"]
            logger.info(f"Candidate Already exists with the id {candidate_id}")
            update_profile_url = f"https://api.breezy.hr/v3/company/{self.company_id}/position/{self.position_id}/candidate/{candidate_id}"
            logger.info("Updating Candidate profile")
            send_request(
                method="PUT",
                url=update_profile_url,
                json=profile.dict(),
                error_message="Couldn't update candidate profile'",
            )
        # If the candidate doesn't already exist we "POST" his profile
        else:
            # Post profile request
            logger.info("Preparing request to push candidate profile")
            push_profile_url = f"https://api.breezy.hr/v3/company/{self.company_id}/position/{self.position_id}/candidates"
            send_request(
                method="POST",
                url=push_profile_url,
                json=profile.dict(),
                error_message="Push Profile to BreezyHr failed",
            )
