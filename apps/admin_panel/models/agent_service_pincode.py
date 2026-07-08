from django.db import models

class AgentServicePincode(models.Model):
    agent = models.ForeignKey('agents.Agent', on_delete=models.CASCADE, related_name='servicePincodes')
    service_pincode = models.CharField(max_length=10)
    city_name = models.CharField(max_length=150)
    selected_areas_json = models.JSONField(null=True, blank=True)
    postal_data_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'agent_service_pincodes'
        unique_together = ('agent', 'service_pincode')

    def __str__(self):
        return f"{self.agent.id} - {self.service_pincode}"
