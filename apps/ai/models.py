"""AI usage analytics."""

from django.db import models

from core.models import TenantModel #inherit from TenantModel to add clinic foreign key field to the model for multi-tenant support


class AIProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    ANTHROPIC = "anthropic", "Anthropic"
    GEMINI = "gemini", "Gemini"
    CACHE = "cache", "Cache"
#Database stores -> openai -> User sees -> OpenAI

class AIOperation(models.TextChoices): # from where does this models come from? It is a choice field for the operation field in the AIUsageLog model. It is a list of possible operations that can be performed by the AI.
    CHAT_COMPLETION = "chat_completion", "Chat Completion"
    EMBEDDING = "embedding", "Embedding"
    INTENT_CLASSIFICATION = "intent_classification", "Intent Classification"


class AIUsageLog(TenantModel): #this is a model for storing the usage logs of the AI. It is a subclass of the TenantModel class.
    session = models.ForeignKey(
        "chatbot.ChatSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
    )
    message = models.ForeignKey(
        "chatbot.ChatMessage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
    )
    provider = models.CharField(
        max_length=50,
        choices=AIProvider.choices,
        default=AIProvider.OPENAI,
    )
    operation = models.CharField(max_length=50, choices=AIOperation.choices)
    model = models.CharField(max_length=50)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    cost_microcents = models.BigIntegerField(default=0)
    cached_response = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta: #
        db_table = "ai_usage_logs"
        indexes = [
            models.Index(fields=["clinic", "created_at"]),
            models.Index(fields=["clinic", "operation", "created_at"]),
            models.Index(fields=["clinic", "cached_response", "created_at"]),
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self) -> str: #__str__ is a special Python function. It tells Python and Django what text should be shown when this object is printed or displayed.
        cache_tag = " [cached]" if self.cached_response else ""
        return f"{self.provider}/{self.operation} — {self.total_tokens} tokens{cache_tag}"  #output that Django shows: openai/chat_completion — 350 tokens


 #This is a string representation of the AIUsageLog model. It is used to display the AIUsageLog model in the admin interface.

 #how does this work?
 #1. The AIUsageLog model is a subclass of the TenantModel class.
 #2. The TenantModel class is a subclass of the models.Model class.
 #3. The models.Model class is a subclass of the object class.
 #4. The object class is the base class for all classes in Python.
 #6. The clinic foreign key field is used to link the AIUsageLog model to the Clinic model.
 #7. The Clinic model is a subclass of the TenantModel class.
 #8. The TenantModel class is a subclass of the models.Model class.
 #9. The models.Model class is a subclass of the object class.
 #10. The object class is the base class for all classes in Python.

 #how the django came to which one is table and which one is model ( AIUsageLog is a model and ai_usage_logs is a table)?
 #1. The Django ORM is used to map the database tables to Python classes.

 #in this code how the django will came to know that AIUsageLog is a table and AIOperation and AIProvider are choices?
 #if we see the code carefully, we will find that AIOperation and AIProvider are defined as models.TextChoices.
 
 #models.TextChoices is a subclass of the models.Choices class.
 #models.Choices is a subclass of the models.Field class.
 #models.Field is a subclass of the models.Model class.
 #models.Model is a subclass of the object class.
 #object class is the base class for all classes in Python.
 #so, AIOperation and AIProvider are defined as models.TextChoices.
