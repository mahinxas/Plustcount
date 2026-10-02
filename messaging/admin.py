from django.contrib import admin

from .models import Campaign, Message, MessageTemplate


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ["title", "channel", "updated_at"]


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ["id", "sender", "channel", "recipient_count", "status", "test_mode", "created_at"]
    list_filter = ["status", "test_mode"]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["id", "client", "to_address", "status", "sent_at"]
    list_filter = ["status"]
    search_fields = ["client__name", "to_address"]
