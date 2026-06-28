import pprint
from pymongo.collection import ObjectId
from vmc.domeo import connect_mongo, retrieve, save


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


def test_retrieve():
    print(retrieve())

def test_save():
    save(retrieve())

def test_drop():
    with connect_mongo() as client:
        db = client.domeo210
        collection = db.metrics
        collection.drop()


# test_filter_query_01()
# test_filter_query_02()
# test_no_filter()
# test_retrieve()
# test_drop()
test_save()