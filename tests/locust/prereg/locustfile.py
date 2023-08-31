"""
Load tests using locust.io.
"""

import urllib3

import faker
from locust import HttpUser, TaskSet, task


urllib3.disable_warnings()
fake = faker.Faker()
faker.providers.phone_number.en_US.Provider.formats = ('888-555-####',)


class Preregister(HttpUser):
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
        self.client.get('/uber/static/js/load-attendee-modal.js', verify=self.verify)
        self.client.get('/uber/static/images/loading.gif', verify=self.verify)
        self.client.get('/uber/static/theme/banner.png', verify=self.verify)
        self.client.get('/uber/static/images/favicon.png', verify=self.verify)

    @task
    def preregister(self):
        self.client.cookies.clear()
        response = self.client.get('/uber/preregistration/form', verify=self.verify)
        assert response.status_code == 200

        csrf_token = self.get_csrf_token(response)

        self.get_static_assets()

        paid = True

        cellphone = fake.phone_number()
        first_name = fake.first_name()
        last_name = fake.last_name()
        zip_code = fake.zipcode()
        data={
            "csrf_token": csrf_token,
            "badge_type": "51352218",
            "amount_extra": "0",
            "extra_donation": "0",
            "first_name": first_name,
            "last_name": last_name,
            "same_legal_name": "1",
            "email": fake.safe_email(),
            "cellphone": cellphone,
            "birthdate": fake.date_time_between('-80y', '-14y').strftime('%Y-%m-%d'),
            "zip_code": zip_code,
            "ec_name": fake.name(),
            "ec_phone": fake.phone_number(),
            "onsite_contact": fake.name(),
            "pii_consent": "1"
        }

        response = self.client.post(
            "/uber/preregistration/validate_attendee",
            verify=self.verify,
            data=data
        )
        assert response.status_code == 200
        
        response = self.client.post(
            "/uber/preregistration/post_form",
            verify=self.verify,
            data=data,
            allow_redirects=False
        )
        if response.status_code == 303:
        
            print(response.headers)
            attendee_id = response.headers['Location'].decode('utf-8').split('attendee_id=')[1]

            response = self.client.get(
                f"/uber/preregistration/additional_info?attendee_id={attendee_id}",
                verify=self.verify
            )
            csrf_token = self.get_csrf_token(response)

            attendee = {
                "attendee_id": attendee_id,
                "csrf_token": csrf_token,
                "staffing": "1",
                "cellphone": cellphone,
                "requested_depts_ids": "252431566",
                "requested_accessibility_services": "1",
                "form_list": "PreregOtherInfo"
            }

            response = self.client.post(
                "/uber/preregistration/validate_attendee",
                verify=self.verify,
                data=attendee
            )
            assert response.status_code == 200
            
            del attendee['form_list']
            response = self.client.post(
                "/uber/preregistration/additional_info",
                verify=self.verify,
                data=attendee
            )

        assert response.status_code == 200

        response = self.client.get(
            "/uber/preregistration/index",
            verify=self.verify
        )
        assert response.status_code == 200
        
        csrf_token = self.get_csrf_token(response)
        
        if paid:
            payment_info = {
                "id": "None",
                "full_name": f"{first_name} {last_name}",
                "zip_code": zip_code,
                "csrf_token": csrf_token
            }
            response = self.client.post(
                "/uber/preregistration/prereg_payment",
                verify=self.verify,
                data=payment_info,
                allow_redirects=False
            )
            assert response.status_code == 303
            
        else:

            response = self.client.get('/uber/preregistration/process_free_prereg', verify=self.verify)
            assert response.status_code == 200

        response = self.client.get('/uber/preregistration/paid_preregistrations?total_cost=125&message=success', verify=self.verify)
        assert response.status_code == 200

