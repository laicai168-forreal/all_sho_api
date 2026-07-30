from app.repositories import collection_repository, user_repository


def _get_user_by_sub_or_raise(sub):
    user = user_repository.get_user_by_sub(sub)
    if not user:
        raise ValueError("User not found")
    return user


def list_collection(sub, page=1, page_size=20, order="desc", keyword=None, car_id=None, metadata=False):
    user = _get_user_by_sub_or_raise(sub)

    if metadata:
        return collection_repository.list_collection_metadata(user["id"])

    if car_id:
        result = collection_repository.get_collection_by_car_id(user["id"], car_id)
        if not result:
            raise ValueError("Car not found")
        return result

    return collection_repository.list_collection_entries(
        user["id"],
        page=page,
        page_size=page_size,
        order=order,
        keyword=keyword,
    )


def list_likes(sub, page=1, page_size=20, keyword=None):
    user = _get_user_by_sub_or_raise(sub)
    return collection_repository.list_liked_cars(
        user["id"],
        page=page,
        page_size=page_size,
        keyword=keyword,
    )


def upsert_collection(sub, payload):
    user = _get_user_by_sub_or_raise(sub)
    items = payload.get("items") or []
    if not items:
        raise ValueError("items array required")

    return collection_repository.upsert_collection_entries(user["id"], items)


def delete_collection(sub, car_id, item_id=None, delete_all=False):
    user = _get_user_by_sub_or_raise(sub)
    if not car_id:
        raise ValueError("carId is required")

    return collection_repository.delete_collection_entry(
        user["id"],
        car_id=car_id,
        item_id=item_id,
        delete_all=delete_all,
    )


def like_collection(sub, car_id):
    user = _get_user_by_sub_or_raise(sub)
    if not car_id:
        raise ValueError("carId is required")
    return collection_repository.like_car(user["id"], car_id)


def dislike_collection(sub, car_id):
    user = _get_user_by_sub_or_raise(sub)
    if not car_id:
        raise ValueError("carId is required")
    return collection_repository.dislike_car(user["id"], car_id)
