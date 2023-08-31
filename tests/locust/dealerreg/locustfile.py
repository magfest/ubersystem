"""
Load tests using locust.io.
"""

import urllib3

import json
import faker
import random
from locust import HttpUser, TaskSet, task


urllib3.disable_warnings()
fake = faker.Faker()
faker.providers.phone_number.en_US.Provider.formats = ('888-555-####',)


class DealerReg(HttpUser):
    min_wait = 1000
    max_wait = 10000

    def on_start(self):
        self.verify = False

    def get_csrf_token(self, response):
        for line in response.iter_lines():
            string = line.decode('utf-8')
            if "csrf_token" in string:
                return string.split("'")[1]


    def get_static_assets(self):
        self.client.get('/uber/static/deps/combined.min.css', verify=self.verify)
        self.client.get('/uber/static_views/styles/main.css', verify=self.verify)
        self.client.get('/uber/static/theme/prereg.css', verify=self.verify)
        self.client.get('/uber/static/theme/prereg_extra.css', verify=self.verify)
        self.client.get('/uber/static/deps/combined.min.js', verify=self.verify)
        self.client.get('/uber/static/js/common-static.js', verify=self.verify)
        self.client.get('/uber/static/images/loading.gif', verify=self.verify)
        self.client.get('/uber/static/theme/banner_2x.png', verify=self.verify)
        self.client.get('/uber/static/images/favicon.png', verify=self.verify)

    @task
    def preregister(self):
        self.client.cookies.clear()
        response = self.client.get(
            '/uber/preregistration/dealer_registration',
            name='/uber/preregistration/dealer_registration',
            verify=self.verify
        )
        assert response.status_code == 200

        csrf_token = self.get_csrf_token(response)

        self.get_static_assets()
        departments = [
            "252431566",
            "59983785",
            "266491407",
            "157456935",
            "168807599",
            "67819226",
            "125461766",
            "201806081",
            "99437969",
            "137781965",
            "39626696",
            "177161930",
            "248958555",
            "181632678",
            "210159096",
            "80341158",
            "145272663",
            "13980098",
            "252033110",
            "224685583"
        ]
        interests = [
            "168807599",
            "59983785",
            "99437969",
            "266227276",
            "124991711",
            "39626696",
            "13980098",
            "155724675",
            "36589291"
        ]
        categories = [
            "95938178",
            "57602999",
            "36020831",
            "187837110",
            "11063151",
            "28701649",
            "225314985",
            "162266210",
            "195322542",
            "232575242",
            "108806493",
            "224685583"
        ]
        other_category = "224685583"
        selected_categories = random.sample(categories, random.randrange(len(categories))+1)

        data={
            "csrf_token": csrf_token,
            "name": fake.company(),
            "description": fake.catch_phrase(),
            "tables": random.choice(["1", "2", "3", "4"]),
            "badges": str(random.randrange(20)+1),
            "website": fake.uri(),
            "categories": selected_categories,
            "categories_text": fake.word(part_of_speech="noun") if other_category in selected_categories else "",
            "wares": fake.paragraph(),
            "special_needs": fake.paragraph() if random.randrange(2) else "",
            "prior_name": fake.company() if random.randrange(2) else "",
            "license": fake.ssn() if random.randrange(2) else "",
            "email_address": fake.company_email(),
            "phone": fake.phone_number(),
            "address1": fake.street_address(),
            "address2": "",
            "country": "United States",
            "region_us": fake.state(),
            "city": fake.city(),
            "zip_code": fake.postcode()
        }

        response = self.client.post(
            "/uber/preregistration/validate_dealer",
            name="/uber/preregistration/validate_dealer",
            verify=self.verify,
            data=data
        )
        assert response.status_code == 200
        assert response.json()['success']
        
        response = self.client.post(
            "/uber/preregistration/post_dealer",
            name="/uber/preregistration/post_dealer",
            verify=self.verify,
            data=data,
            allow_redirects=False
        )
        assert response.status_code == 303
    
        dealer_id = response.headers['Location'].split('dealer_id=')[1]

        response = self.client.get(
            f"/uber/preregistration/form",
            name=f"/uber/preregistration/form",
            params={"dealer_id": dealer_id},
            verify=self.verify
        )
        csrf_token = self.get_csrf_token(response)

        cellphone = fake.phone_number()
        first_name = fake.first_name()
        last_name = fake.last_name()
        is_legal_name = "1" if random.randrange(2) else ""
        data={
            "group_id": dealer_id,
            "csrf_token": csrf_token,
            "badge_type": "2",
            "first_name": first_name,
            "last_name": last_name,
            "same_legal_name": is_legal_name,
            "email": fake.email(),
            "cellphone": cellphone,
            "birthdate": fake.date_time_between('-80y', '-14y').strftime('%Y-%m-%d'),
            "zip_code": fake.postcode(),
            "ec_name": fake.name(),
            "ec_phone": fake.phone_number(),
            "onsite_contact": fake.name(),
            "pii_consent": "1"
        }
        if not is_legal_name:
            data["legal_name"] = fake.name()


        response = self.client.post(
            "/uber/preregistration/validate_attendee",
            name="/uber/preregistration/validate_attendee",
            verify=self.verify,
            data=data
        )
        assert response.status_code == 200

        response = self.client.post(
            "/uber/preregistration/post_form",
            name="/uber/preregistration/post_form",
            verify=self.verify,
            data=data,
            allow_redirects=False
        )
        assert response.status_code == 303

        response = self.client.get(
            "/uber/preregistration/additional_info",
            name="/uber/preregistration/additional_info",
            params={"group_id": dealer_id},
            verify=self.verify
        )
        assert response.status_code == 200

        is_staffing = "1" if random.randrange(2) else ""
        additional_info = {
            "group_id": dealer_id,
            "csrf_token": self.get_csrf_token(response),
            "staffing": is_staffing,
            "cellphone": fake.phone_number(),
            "form_list": "PreregOtherInfo"
        }
        if is_staffing:
            additional_info["requested_depts_ids"] = random.sample(departments, random.randrange(len(departments)+1))
        additional_info["interests"] = random.sample(interests, random.randrange(len(interests)+1))
        if random.randrange(2):
            additional_info["requested_accessibility_services"] = "1"

        response = self.client.post(
            "/uber/preregistration/validate_attendee",
            name="/uber/preregistration/validate_attendee",
            verify=self.verify,
            data=additional_info
        )
        assert response.status_code == 200

        response = self.client.post(
            "/uber/preregistration/additional_info",
            name="/uber/preregistration/additional_info",
            verify=self.verify,
            data=additional_info,
            allow_redirects=False
        )
        assert response.status_code == 303

        response = self.client.get(
            "/uber/preregistration/finish_dealer_reg",
            name="/uber/preregistration/finish_dealer_reg",
            params={"id": dealer_id},
            verify=self.verify,
            allow_redirects=False
        )
        assert response.status_code == 303

        response = self.client.get(
            "/uber/preregistration/dealer_confirmation",
            name="/uber/preregistration/dealer_confirmation",
            params={"id": dealer_id},
            verify=self.verify
        )
        assert response.status_code == 200