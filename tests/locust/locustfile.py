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
        self.verify = not(
            '//localhost' in self.client.base_url or
            '//127.0.0.1' in self.client.base_url)
        self.get_preregistration()

    @task(4)
    def get_preregistration(self):
        self.client.get('/uber/preregistration/form', verify=self.verify)

    @task(1)
    def post_preregistration(self):
        response = self.client.post(
            '/uber/preregistration/form',
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
                'birthdate': fake.date_time_between(
                    '-80y', '-14y').strftime('%Y-%m-%d'),
                'email': fake.safe_email(),
                'zip_code': fake.zipcode(),
                'ec_name': fake.name(),
                'ec_phone': fake.phone_number(),
                'cellphone': fake.phone_number(),
                'found_how': fake.catch_phrase(),
                'comments': fake.paragraph(),
                'extra_donation': ''})


class AttendeeLocust(HttpLocust):
    task_set = AttendeeBehavior
