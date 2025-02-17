from typing import Iterator, Dict, Any, Optional
from pydantic import Field
import requests

from ...core.error import PullError, PushError
from ...core.action import PullJobsBaseAction, PushProfileBaseAction
from ...core.auth import XTaleezAuth
from ...utils.logger import get_logger
from ...utils.clean_text import remove_html_tags
from ...utils.hrflow import generate_workflow_response
from datetime import datetime
from ...utils.schemas import HrflowJob, HrflowProfile
from .schemas import TaleezJobModel, TaleezCandidateModel

logger = get_logger()


class PullJobsAction(PullJobsBaseAction):
    auth: XTaleezAuth
    page: int = Field(0, description="Page number. Start at '0'")
    page_size: int = Field(
        100, description="Page size. Max size of the list returned. Max value : 100"
    )

    def pull(self) -> Iterator[TaleezJobModel]:
        """
        Pull jobs from a Taleez jobs owner endpoint

        Returns list of all jobs that have been pulled
        """

        # Prepare request
        session = requests.Session()
        pull_jobs_request = requests.Request()
        pull_jobs_request.method = "GET"
        pull_jobs_request.url = f"https://api.taleez.com/0/jobs?page={self.page}&pageSize={self.page_size}&withDetails=true"
        pull_jobs_request.auth = self.auth
        prepared_request = pull_jobs_request.prepare()

        # Send request
        response = session.send(prepared_request)

        if not response.ok:
            raise PullError(response, message="Failed to get jobs")

        response_dict = response.json()
        logger.info(f"Total found: {response_dict['listSize']}")
        job_list = response_dict["list"]
        job_obj_iter = map(TaleezJobModel.parse_obj, job_list)

        return job_obj_iter

    def format(self, data: TaleezJobModel) -> HrflowJob:
        """
        Format a job into the hrflow job object format

        Args:
            data (TaleezJobModel): a taleez job object form

        Returns:
            HrflowJob: a hrflow job object form
        """

        job = dict()
        data = data.dict()

        # Job basic information
        job["name"] = data.get("label")
        job["reference"] = str(data["id"])
        job["url"] = data.get("url")
        job["summary"] = None

        # Job Location
        city = data.get("city")
        country = data.get("country")
        postalcode = data.get("postalCode")
        lat = data.get("lat")
        lng = data.get("lng")
        geojson = dict(country=country, postalcode=postalcode)
        job["location"] = dict(text=city, lat=lat, lng=lng, geojson=geojson)

        # Job Sections
        job["sections"] = []

        def create_section(field_name: str):
            section_name = "taleez_{}".format(field_name)
            section_tile = section_name
            description = remove_html_tags(data.get(field_name))
            if description is not None:
                section = dict(
                    name=section_name, title=section_tile, description=description
                )
                job["sections"].append(section)

        create_section("jobDescription")
        create_section("profileDescription")
        create_section("companyDescription")

        # Job Tags
        job["tags"] = []

        def create_tag(field_name: str):
            tag_name = "taleez_{}".format(field_name)
            tag_value = data.get(field_name)
            if tag_value is not None:
                tag = dict(name=tag_name, value=tag_value)
                job["tags"].append(tag)

        create_tag("contract")
        create_tag("profile")
        create_tag("contractLength")
        create_tag("fullTime")
        create_tag("workHours")
        create_tag("qualification")
        create_tag("remote")
        create_tag("recruiterId")
        create_tag("companyLabel")
        create_tag("urlApplying")
        create_tag("currentStatus")

        def seconds_to_isoformat(seconds: int) -> str:
            """
            Seconds_to_iso8601 converts seconds to datetime ISOFORMAT

            Args:
                seconds : datetime in seconds since epoch

            returns datetime in isoformat for example for 1642104049 secs returns '2022-01-13T20:00:49'
            """
            return datetime.utcfromtimestamp(seconds).isoformat()

        # datetime fields
        job["created_at"] = seconds_to_isoformat(data.get("dateCreation"))
        job["updated_at"] = seconds_to_isoformat(data.get("dateLastPublish"))
        job_obj = HrflowJob.parse_obj(job)
        return job_obj


class PushProfileAction(PushProfileBaseAction):
    recruiter_id: int = Field(
        ..., description="ID of the person recruiting the candidate, mandatory"
    )
    job_id: Optional[int] = Field(
        None, description="ID of the job to add a candidate to"
    )

    def format(self, data: HrflowProfile) -> TaleezCandidateModel:
        """
        Format a Hrflow profile object into a Taleez profile object

        Returns: TaleezCandidateModel a Taleez profile object form
        """
        profile = dict()
        data = data.dict()
        info = data.get("info")
        profile["firstName"] = info.get("first_name")
        profile["lastName"] = info.get("last_name")
        profile["email"] = info.get("email")
        profile["number"] = info.get("phone")
        profile["lang"] = data.get("text_language")
        profile["recruiterId"] = self.recruiter_id

        profile["socialLinks"] = dict()

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
                        profile["socialLinks"][type] = link
            attachments = info.get("attachments")
            if isinstance(attachments, list):
                for attachment in attachments:
                    file_name = attachment.get("file_name")
                    public_url = attachment.get("public_url")
                    if isinstance(public_url, str):
                        profile["socalLinks"][file_name] = public_url

        format_urls()
        profile_obj = TaleezCandidateModel.parse_obj(profile)
        return profile_obj

    def push(self, data):
        """
        Push a profile into a Taleez CVTheque or a Taleez job offer as a candidate

        Args:
            data (TaleezCandidateModel): a Taleez profile form
        """
        profile = next(data)

        # Prepare request
        session = requests.Session()
        push_profile_request = requests.Request()
        push_profile_request.method = "POST"
        push_profile_request.url = f"https://api.taleez.com/0/candidates"
        push_profile_request.auth = self.auth
        push_profile_request.json = profile.dict()
        prepared_push_profile_request = push_profile_request.prepare()

        # Send request
        push_profile_response = session.send(prepared_push_profile_request)

        if not push_profile_response.ok:
            raise PushError(push_profile_response)

        if self.job_id is not None:
            push_profile_response_dict = push_profile_response.json()
            candidate_id = push_profile_response_dict["id"]
            # Prepare request
            add_profile_request = requests.Request()
            add_profile_request.method = "POST"
            add_profile_request.url = (
                f"https://api.taleez.com/0/jobs/{self.job_id}/candidates"
            )
            add_profile_request.auth = self.auth
            add_profile_request.json = dict(ids=[candidate_id])
            prepared_add_profile_request = add_profile_request.prepare()

            # Send request
            add_profile_response = session.send(prepared_add_profile_request)

            if not add_profile_response.ok:
                raise PushError(add_profile_response, job_id=self.job_id)
