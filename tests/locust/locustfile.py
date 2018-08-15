"""
Load tests using locust.io.
"""
import faker
from locust import HttpLocust, TaskSet, task


fake = faker.Faker()
faker.providers.phone_number.en_US.Provider.formats = ('888-555-####',)


class AttendeeBehavior(TaskSet):
    min_wait = 1000
    max_wait = 10000

    def on_start(self):
        self.verify = False
        self.get_preregistration()

    def get_static_assets(self):
        self.client.get('/static/deps/combined.min.css', verify=self.verify)
        self.client.get('/static_views/styles/main.css', verify=self.verify)
        self.client.get('/static/theme/prereg.css', verify=self.verify)
        self.client.get('/static/theme/prereg_extra.css', verify=self.verify)
        self.client.get('/static/deps/combined.min.js', verify=self.verify)
        self.client.get('/static/js/common-static.js', verify=self.verify)
        self.client.get('/static/theme/tile-background.png', verify=self.verify)
        self.client.get('/static/images/loading.gif', verify=self.verify)
        self.client.get('/static/theme/banner_2x.png', verify=self.verify)

    @task(3)
    def get_preregistration(self):
        self.client.get('/preregistration/form', verify=self.verify)
        self.get_static_assets()

    @task(1)
    def post_preregistration(self):
        self.get_preregistration()

        self.client.post(
            '/preregistration/post_form',
            verify=self.verify,
            data={
                'badge_type': '51352218',
                'name': '',
                'badges': '1',
                'first_name': fake.first_name(),
                'last_name': fake.last_name(),
                'same_legal_name': "Yep, that's right",
                'legal_name': '',
                'amount_extra': '0',
                'badge_printed_name': '',
                'affiliate': '',
                'shirt': '0',
                'birthdate': fake.date_time_between('-80y', '-14y').strftime('%Y-%m-%d'),
                'email': fake.safe_email(),
                'zip_code': fake.zipcode(),
                'ec_name': fake.name(),
                'ec_phone': fake.phone_number(),
                'cellphone': fake.phone_number(),
                'found_how': fake.catch_phrase(),
                'comments': fake.paragraph(),
                'extra_donation': '',
                'pii_consent': '1',
            }
        )

        self.client.get('/preregistration/index', verify=self.verify)
        self.client.get('/preregistration/process_free_prereg', verify=self.verify)
        self.client.get('/preregistration/paid_preregistrations?payment_received=0', verify=self.verify)


class AttendeeLocust(HttpLocust):
    task_set = AttendeeBehavior
