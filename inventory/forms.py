from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import Item, Location, Lot, OpenedContainer, StockCount, StockCountLine


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")


class ReceiveForm(forms.Form):
    item = forms.ModelChoiceField(queryset=Item.objects.none())
    lot_number = forms.CharField(max_length=80)
    location = forms.ModelChoiceField(queryset=Location.objects.none())
    quantity = forms.DecimalField(min_value=0.01, decimal_places=2, max_digits=12)
    manufacturer_expiry = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(max_length=255, initial="Goods received")
    reference = forms.CharField(max_length=80, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = Item.objects.filter(
            organization=organization, is_active=True
        )
        self.fields["location"].queryset = Location.objects.filter(
            organization=organization, is_active=True
        )
        for name, field in self.fields.items():
            if name != "notes":
                field.widget.attrs.setdefault("class", "input")
            else:
                field.widget.attrs.setdefault("class", "textarea")


class IssueForm(forms.Form):
    SOURCE_LOT = "lot"
    SOURCE_OPENED = "opened"

    source_type = forms.ChoiceField(
        choices=[(SOURCE_LOT, "Sealed lot"), (SOURCE_OPENED, "Opened container")],
        widget=forms.RadioSelect,
        initial=SOURCE_LOT,
    )
    lot = forms.ModelChoiceField(queryset=Lot.objects.none(), required=False)
    opened_container = forms.ModelChoiceField(
        queryset=OpenedContainer.objects.none(), required=False
    )
    quantity = forms.DecimalField(min_value=0.01, decimal_places=2, max_digits=12)
    reason = forms.CharField(max_length=255, initial="Issued to bench")
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = Lot.objects.filter(
            organization=organization, is_active=True, quantity_on_hand__gt=0
        ).select_related("item", "location")
        self.fields["opened_container"].queryset = OpenedContainer.objects.filter(
            organization=organization, is_active=True, quantity_remaining__gt=0
        ).select_related("item", "lot", "location")
        for name, field in self.fields.items():
            if name in {"notes"}:
                field.widget.attrs.setdefault("class", "textarea")
            elif name != "source_type":
                field.widget.attrs.setdefault("class", "input")

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("source_type")
        if source == self.SOURCE_LOT and not cleaned.get("lot"):
            self.add_error("lot", "Select a sealed lot.")
        if source == self.SOURCE_OPENED and not cleaned.get("opened_container"):
            self.add_error("opened_container", "Select an opened container.")
        return cleaned


class OpenContainerForm(forms.Form):
    lot = forms.ModelChoiceField(queryset=Lot.objects.none())
    quantity = forms.DecimalField(min_value=0.01, decimal_places=2, max_digits=12)
    container_label = forms.CharField(max_length=80)
    opened_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    expiry_rule_days = forms.IntegerField(
        required=False,
        min_value=1,
        help_text="Leave blank to use the item default.",
    )
    expiry_rule_source = forms.CharField(
        max_length=255,
        required=False,
        help_text="Leave blank to use the item default.",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = Lot.objects.filter(
            organization=organization, is_active=True, quantity_on_hand__gt=0
        ).select_related("item", "location")
        for name, field in self.fields.items():
            if name == "notes":
                field.widget.attrs.setdefault("class", "textarea")
            else:
                field.widget.attrs.setdefault("class", "input")


class AdjustmentForm(forms.Form):
    SOURCE_LOT = "lot"
    SOURCE_OPENED = "opened"

    source_type = forms.ChoiceField(
        choices=[(SOURCE_LOT, "Sealed lot"), (SOURCE_OPENED, "Opened container")],
        widget=forms.RadioSelect,
        initial=SOURCE_LOT,
    )
    lot = forms.ModelChoiceField(queryset=Lot.objects.none(), required=False)
    opened_container = forms.ModelChoiceField(
        queryset=OpenedContainer.objects.none(), required=False
    )
    quantity_delta = forms.DecimalField(
        decimal_places=2,
        max_digits=12,
        help_text="Positive to increase, negative to decrease.",
    )
    reason = forms.CharField(max_length=255)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = Lot.objects.filter(
            organization=organization
        ).select_related("item", "location")
        self.fields["opened_container"].queryset = OpenedContainer.objects.filter(
            organization=organization
        ).select_related("item", "lot")
        for name, field in self.fields.items():
            if name == "notes":
                field.widget.attrs.setdefault("class", "textarea")
            elif name != "source_type":
                field.widget.attrs.setdefault("class", "input")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("quantity_delta") == 0:
            self.add_error("quantity_delta", "Cannot be zero.")
        source = cleaned.get("source_type")
        if source == self.SOURCE_LOT and not cleaned.get("lot"):
            self.add_error("lot", "Select a sealed lot.")
        if source == self.SOURCE_OPENED and not cleaned.get("opened_container"):
            self.add_error("opened_container", "Select an opened container.")
        return cleaned


class StockCountForm(forms.ModelForm):
    class Meta:
        model = StockCount
        fields = ["location", "counted_on", "notes"]
        widgets = {
            "counted_on": forms.DateInput(attrs={"type": "date", "class": "input"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "textarea"}),
            "location": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.objects.filter(
            organization=organization, is_active=True
        )


class StockCountLineForm(forms.ModelForm):
    class Meta:
        model = StockCountLine
        fields = ["counted_quantity", "variance_reason"]
        widgets = {
            "counted_quantity": forms.NumberInput(attrs={"class": "input", "step": "0.01"}),
            "variance_reason": forms.TextInput(attrs={"class": "input"}),
        }
