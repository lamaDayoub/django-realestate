
# notifications/signals.py
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from django.db import transaction # For atomic updates
from django.db.models.signals import m2m_changed
from users.models import User
from properties.models import Property, FavoriteProperty,Rating
from .models import Notification
from .tasks import dispatch_notification_task
from django.db.models import Avg, Count 

_old_property_values = {}

@receiver(pre_save, sender=Property)
def pre_save_property_handler(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_instance = Property.objects.get(pk=instance.pk)
            _old_property_values[instance.pk] = {
                'active': old_instance.active,
                'price': old_instance.price,
            }
        except Property.DoesNotExist:
            _old_property_values[instance.pk] = None
        print(f"DEBUG: Pre-save for Property {instance.pk}. Old values captured: {_old_property_values[instance.pk]}")


@receiver(post_save, sender=Property)
def post_save_property_handler(sender, instance, created, **kwargs):
    owner = instance.owner
    rater_user_id = kwargs.get('rater_user_id', None) 
    if created:
        if instance.active:
            notification_message = f"Your new property '{instance.ptype} in {instance.city}' has been listed successfully!"
            notification_type = Notification.NotificationType.PROPERTY_STATUS

            notification = Notification.objects.create(
                recipient=owner,
                notification_type=notification_type,
                message=notification_message,
                content_type=ContentType.objects.get_for_model(instance),
                object_id=instance.pk
            )
            dispatch_notification_task.delay(notification.pk)
            print(f"DEBUG: Dispatched notification for new property: {notification_message}")

    else:
        old_values = _old_property_values.pop(instance.pk, None)
        if old_values:
            if old_values['active'] != instance.active:
                status_text = "activated" if instance.active else "deactivated"
                notification_message = f"Your property '{instance.ptype} in {instance.city}' has been {status_text} successfully."
                notification_type = Notification.NotificationType.PROPERTY_STATUS

                notification = Notification.objects.create(
                    recipient=owner,
                    notification_type=notification_type,
                    message=notification_message,
                    content_type=ContentType.objects.get_for_model(instance),
                    object_id=instance.pk
                )
                dispatch_notification_task.delay(notification.pk)
                print(f"DEBUG: Dispatched notification for property status change: {notification_message}")
                favorited_users_for_status_change = instance.favorited_by.all()
                favorited_users_for_status_change = favorited_users_for_status_change.exclude(pk=owner.pk) # Exclude owner

                if favorited_users_for_status_change.exists():
                    notification_message_favoriter_status = (
                        f"A property you favorited: '{instance.ptype} in {instance.city}' "
                        f"has been {status_text}."
                    )
                    for favored_user in favorited_users_for_status_change:
                        notification = Notification.objects.create(
                            recipient=favored_user,
                            notification_type=notification_type, # Reuse PROPERTY_STATUS type
                            message=notification_message_favoriter_status,
                            content_type=ContentType.objects.get_for_model(instance),
                            object_id=instance.pk
                        )
                        dispatch_notification_task.delay(notification.pk)
                        print(f"DEBUG: Dispatched notification for property status change (to favoriter {favored_user.email}): {notification_message_favoriter_status}")
                else:
                    print(f"DEBUG: Property {instance.pk} status changed, but no non-owner favoriters to notify.")

            if old_values['price'] != instance.price:
                favorited_users = instance.favorited_by.all() # Accesses related_name='favorited_by' from Property

                # Do not notify the owner about their own price change
                favorited_users = favorited_users.exclude(pk=owner.pk) 

                notification_type = Notification.NotificationType.PROPERTY_PRICE_CHANGE

                for favored_user in favorited_users:
                    notification_message = (
                        f"Price updated on a property you favorited: '{instance.ptype} in {instance.city}'. "
                        f"New price: ${instance.price}."
                    )
                    notification = Notification.objects.create(
                        recipient=favored_user, # <--- Recipient is the FAVORITER
                        notification_type=notification_type,
                        message=notification_message,
                        content_type=ContentType.objects.get_for_model(instance),
                        object_id=instance.pk
                    )
                    dispatch_notification_task.delay(notification.pk)
                    print(f"DEBUG: Dispatched notification for property price change (to favoriter {favored_user.email}): {notification_message}")

                # If no one favorited (or only owner did), no notification is sent.
                if not favorited_users.exists():
                    print(f"DEBUG: Price changed for Property {instance.pk}, but no non-owner favoriters to notify.")
            # --- END NEW ---
               
                
        else:
            print(f"WARNING: Old property values not found for instance {instance.pk} during post_save. Price/active change notifications might be missed.")


@receiver(post_save, sender=FavoriteProperty)
# @receiver(m2m_changed, sender=User.favorite_properties.through,created)
def post_save_favorite_property_handler(sender, instance, created, **kwargs):
    if created:
        property_obj = instance.property
        favoriter_user = instance.user
        owner = property_obj.owner

        if owner == favoriter_user:
            print(f"DEBUG: Owner {owner.email} favorited their own property {property_obj.pk}. No notification dispatched.")
            return

        notification_message = (
            f"Your property '{property_obj.ptype} in {property_obj.city}' "
            f"has been favorited by {favoriter_user.profile.first_name} {favoriter_user.profile.last_name if hasattr(favoriter_user, 'profile') and favoriter_user.profile else ''}!"
        )
        notification_type = Notification.NotificationType.PROPERTY_FAVORITED

        notification = Notification.objects.create(
            recipient=owner,
            notification_type=notification_type,
            message=notification_message,
            content_type=ContentType.objects.get_for_model(property_obj),
            object_id=property_obj.pk
        )
        dispatch_notification_task.delay(notification.pk)
        print(f"DEBUG: Dispatched notification for property favorited: {notification_message}")
        
@receiver(post_save, sender=Rating) #  Signal for Rating model
def post_save_rating_handler(sender, instance, created, **kwargs):
    """
    Recalculates Property's average rating and dispatches notification when a Rating is created.
    """
    property_obj = instance.property
    rater_user = instance.user # The user who submitted the rating
    owner = property_obj.owner # The owner of the property

    # --- Recalculate Property's Average Rating ---
    # Use aggregation to get the current average and count of all ratings for this property
    # This is robust for creation, update, or deletion of individual ratings
    aggregation_result = Rating.objects.filter(property=property_obj).aggregate(
        avg_value=Avg('value'),
        count_value=Count('value')
    )

    new_average_rating = aggregation_result['avg_value'] if aggregation_result['avg_value'] is not None else 0.00
    new_rating_count = aggregation_result['count_value'] if aggregation_result['count_value'] is not None else 0

    # Update the Property instance directly
    property_obj.rating = new_average_rating
    # We don't need to update total_rating_sum/rating_count on Property anymore, as they are gone.
    property_obj.save(update_fields=['rating']) # Save the updated average rating

    print(f"DEBUG: Property {property_obj.pk} average rating updated to {property_obj.rating} (from {new_rating_count} ratings).")

    # --- Dispatch Notification (only on creation of a new rating) ---
    if created:
        notification_message = (
            f"Your property '{property_obj.ptype} in {property_obj.city}' "
            f"received a new rating of {instance.value} stars from {rater_user.profile.first_name} {rater_user.profile.last_name if hasattr(rater_user, 'profile') and rater_user.profile else ''}!"
            f" New average rating: {property_obj.rating:.2f}."
        )
        notification_type = Notification.NotificationType.PROPERTY_RATED

        notification = Notification.objects.create(
            recipient=owner,
            notification_type=notification_type,
            message=notification_message,
            content_type=ContentType.objects.get_for_model(property_obj), # Link to the Property object
            object_id=property_obj.pk
            # The rater's info is embedded in the message.
        )
        dispatch_notification_task.delay(notification.pk)
        print(f"DEBUG: Dispatched notification for property rated: {notification_message}")