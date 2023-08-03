import pprint

from domeo import connect_mongo
from pymongo.collection import ObjectId

from domeo import new_retrieve, retrieve


def collect(filters: dict = {}, fields: dict = {}):
    with connect_mongo() as client:
        db = client.domeo210
        collection = db.metrics
        query = [m for m in collection.find(filters, fields)]
    return query


def test_filter_query_01():
    print(collect({"_id": ObjectId('64ca2f39e52754e1ed7cd747')}))


def test_filter_query_02():
    pprint.pprint(collect({'data.name': 'VERSION'}, {'data': {"$elemMatch": {'name': 'VERSION'}}}))


def test_no_filter():
    print(collect())


def test_new_retrieve():
    new_retrieve()


def test_retrieve():
    retrieve()


# test_filter_query_01()
# test_filter_query_02()
# test_no_filter()
test_retrieve()
