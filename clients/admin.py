from django.contrib import admin

from .models import Client, ClientAssignment


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["name", "business_id", "email", "language", "owner", "opted_out"]
    list_filter = ["language", "company_type", "opted_out", "owner"]
    search_fields = ["name", "business_id", "email", "phone"]


@admin.register(ClientAssignment)
class ClientAssignmentAdmin(admin.ModelAdmin):
    list_display = ["client", "from_user", "to_user", "changed_by", "changed_at"]
    readonly_fields = [f.name for f in ClientAssignment._meta.fields]
