"""Spring PetClinic functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Drives every page of the pinned 1.5.x PetClinic: the welcome page, owner search (all, one match, several, none), owner
create and edit (valid and invalid), owner details, pet create and edit (valid, missing fields, duplicate name, every pet
type), visit create (valid and missing description), the vet list as HTML, JSON and XML, and the deliberate crash page.
The seed data (db/hsqldb/data.sql) is reloaded at every start: owners 1-10, pet types cat .. hamster.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, unique  # noqa: E402

suite = Suite("PetClinic", os.environ.get("PETCLINIC_BASE_URL", "http://localhost:8080"), ready_path="/")
CONTAINER_NAME = "spring-petclinic-app"

PET_TYPES = ("cat", "dog", "lizard", "snake", "bird", "hamster")
OWNER = {"firstName": "Ada", "lastName": "Lovelace", "address": "12 Engine St.", "city": "London",
         "telephone": "6085550100"}


def new_owner(c, **overrides):
    """Create an owner; returns (owner id, last name)."""
    form = dict(OWNER, lastName=unique("Lovelace"), **overrides)
    page = c.post("/owners/new", form, contains=form["lastName"])
    m = re.search(r"/owners/(\d+)$", page.url.split(";")[0])  # redirected to the new owner's page
    if not m:
        raise UsecaseFailed(f"creating an owner landed on {page.url}")
    return m.group(1), form["lastName"]


def new_pet(c, owner_id, name=None, pet_type="cat", birth="2020-01-15", **checks):
    name = name or unique("Rex")
    page = c.post(f"/owners/{owner_id}/pets/new", {"name": name, "birthDate": birth, "type": pet_type}, **checks)
    return name, page


def pet_ids(page):
    return re.findall(r"pets/(\d+)/edit", page.text)


@suite.usecase("ViewHome")
def view_home(c):
    c.get("/", contains="Welcome")
    c.get("/owners/find", contains="Find Owners")


@suite.usecase("Find_Owner")
def find_owner(c):
    c.get("/owners", {"lastName": ""}, contains=["Franklin", "Davis", "Owners"])  # empty search lists everyone
    c.get("/owners", {"lastName": "Franklin"}, contains=["George Franklin", "Owner Information"])  # one: details
    page = c.get("/owners", {"lastName": "Davis"}, contains="Owners")  # several: the list
    if not ("Betty Davis" in page.text and "Harold Davis" in page.text):
        raise UsecaseFailed("searching Davis did not list both Davis owners")
    c.get("/owners", {"lastName": "NoSuchOwner"}, contains="has not been found")


@suite.usecase("Add_Owner")
def add_owner(c):
    c.get("/owners/new", contains="Owner")
    owner_id, last = new_owner(c)
    c.get(f"/owners/{owner_id}", contains=[last, "12 Engine St."])
    c.post("/owners/new", dict(OWNER, telephone="not-a-number"), contains="numeric value out of bounds")
    c.post("/owners/new", dict(OWNER, firstName="", address=""), contains="may not be empty")


@suite.usecase("Edit_Owner")
def edit_owner(c):
    owner_id, last = new_owner(c)
    c.get(f"/owners/{owner_id}/edit", contains=last)
    c.post(f"/owners/{owner_id}/edit", dict(OWNER, lastName=last, city="Cambridge"), contains="Cambridge")
    c.post(f"/owners/{owner_id}/edit", dict(OWNER, lastName=last, telephone="12ab"), contains="numeric value out of bounds")


@suite.usecase("View_Owner")
def view_owner(c):
    for owner_id in range(1, 11):
        c.get(f"/owners/{owner_id}", contains="Owner Information")


@suite.usecase("Add_Pet")
def add_pet(c):
    owner_id, _ = new_owner(c)
    c.get(f"/owners/{owner_id}/pets/new", contains=["Pet", "hamster"])
    for pet_type in PET_TYPES:
        name, page = new_pet(c, owner_id, pet_type=pet_type)
        if name not in page.text:
            raise UsecaseFailed(f"the new {pet_type} is not on the owner page")
    taken, _ = new_pet(c, owner_id)
    new_pet(c, owner_id, name=taken, contains="is already in use")
    c.post(f"/owners/{owner_id}/pets/new", {"name": "", "birthDate": "", "type": "cat"}, contains="required")


@suite.usecase("Edit_Pet")
def edit_pet(c):
    owner_id, _ = new_owner(c)
    name, page = new_pet(c, owner_id, pet_type="dog")
    pet_id = pet_ids(page)[0]
    c.get(f"/owners/{owner_id}/pets/{pet_id}/edit", contains=name)
    renamed = name + "y"
    c.post(f"/owners/{owner_id}/pets/{pet_id}/edit", {"id": pet_id, "name": renamed, "birthDate": "2019-05-05",
                                                     "type": "bird"}, contains=renamed)
    c.post(f"/owners/{owner_id}/pets/{pet_id}/edit", {"id": pet_id, "name": "", "birthDate": "2019-05-05",
                                                     "type": "bird"}, contains="required")


@suite.usecase("Add_Visit")
def add_visit(c):
    owner_id, _ = new_owner(c)
    _, page = new_pet(c, owner_id, pet_type="hamster")
    pet_id = pet_ids(page)[0]
    c.get(f"/owners/{owner_id}/pets/{pet_id}/visits/new", contains=["Visit", "Previous Visits"])
    note = unique("Checkup ")
    c.post(f"/owners/{owner_id}/pets/{pet_id}/visits/new", {"date": "2026-11-27", "description": note}, contains=note)
    c.post(f"/owners/{owner_id}/pets/{pet_id}/visits/new", {"date": "2026-11-28", "description": ""},
           contains="may not be empty")
    c.get("/owners/1/pets/1/visits/new", contains="Leo")  # a seeded pet with seeded visits


@suite.usecase("ViewVets")
def view_vets(c):
    c.get("/vets.html", contains=["Veterinarians", "James Carter"])
    vets = c.get("/vets.json", headers={"Accept": "application/json"}).json()
    if not vets.get("vetList"):
        raise UsecaseFailed(f"/vets.json returned {vets}")
    c.get("/vets.xml", headers={"Accept": "application/xml"}, contains="Carter")


@suite.usecase("Error")
def error_page(c):
    c.get("/oups", expect=500, contains="Expected: controller used to showcase what happens when an exception is thrown")
    c.get("/owners/999999", expect=(200, 500))  # an unknown owner renders an empty owner or fails
    c.get("/no-such-page", expect=404)


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
