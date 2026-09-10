"""Compare small and full owner lists: data growth must not add per-row queries."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models import Goal, StudyNote


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "route"), [(StudyNote, "/api/notes/"), (Goal, "/api/goals/")])
def test_owned_list_query_count_does_not_grow_per_item(student, client_for, record_property, model, route):
    client = client_for(student)
    model.objects.create(owner=student, title="Synthetic baseline item")
    # Warm auth/content type caches before comparing database work.
    assert client.get(route).status_code == 200
    with CaptureQueriesContext(connection) as small:
        assert client.get(route).status_code == 200
    model.objects.bulk_create([model(owner=student, title=f"Synthetic item {index}") for index in range(24)])
    with CaptureQueriesContext(connection) as full:
        assert client.get(route).status_code == 200
    record_property("database_vendor", connection.vendor)
    record_property("small_list_queries", len(small))
    record_property("full_list_queries", len(full))
    assert len(full) <= len(small) + 2, "Owner list introduces queries proportional to its item count"
