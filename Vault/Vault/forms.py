from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.exceptions import ValidationError
from .models import Expense, SecurityProfile, Friendship, ExpenseGroup, SavingsGoal

class AddFriendForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter friend\'s username'}))

class GroupForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        label="Group Members (Friend List)"
    )

    class Meta:
        model = ExpenseGroup
        fields = ['name', 'members']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Miami Trip'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(GroupForm, self).__init__(*args, **kwargs)
        if user:
            friends_initiated = Friendship.objects.filter(user=user, status='Accepted').values_list('friend_id', flat=True)
            friends_received = Friendship.objects.filter(friend=user, status='Accepted').values_list('user_id', flat=True)
            friend_ids = list(friends_initiated) + list(friends_received)
            self.fields['members'].queryset = User.objects.filter(id__in=friend_ids)

class GoalForm(forms.ModelForm):
    class Meta:
        model = SavingsGoal
        fields = ['name', 'target_amount', 'target_date']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Vacation Fund'}),
            'target_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'target_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

class AddFundsForm(forms.Form):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01, widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Amount to add'}))

class CustomLoginForm(AuthenticationForm):
    def clean(self):
        username = self.cleaned_data.get('username')
        if username and not User.objects.filter(username=username).exists():
            raise ValidationError("This user doesn't exist.")
        return super().clean()

class CustomRegistrationForm(UserCreationForm):
    q1 = forms.CharField(label="1. What is your mother's maiden name?", max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    q2 = forms.CharField(label="2. What was the name of your first pet?", max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    q3 = forms.CharField(label="3. In what city were you born?", max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
            SecurityProfile.objects.create(
                user=user,
                q1_answer=self.cleaned_data['q1'].strip().lower(),
                q2_answer=self.cleaned_data['q2'].strip().lower(),
                q3_answer=self.cleaned_data['q3'].strip().lower(),
            )
        return user

class ExpenseForm(forms.ModelForm):
    split_with = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        label="Split With Friends"
    )

    class Meta:
        model = Expense
        fields = ['title', 'amount', 'due_date', 'category', 'expense_type', 'status', 'payment_method', 'is_autopay', 'is_shared', 'notes', 'split_type', 'group']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'expense_type': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'is_autopay': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_shared': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional notes...'}),
            'split_type': forms.Select(attrs={'class': 'form-select'}),
            'group': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(ExpenseForm, self).__init__(*args, **kwargs)
        filtered_categories = [choice for choice in Expense.CATEGORY_CHOICES if choice[0] != 'Credit Card']
        self.fields['category'].choices = filtered_categories
        
        if user:
            # Get friends where user initiated and status is accepted
            friends_initiated = Friendship.objects.filter(user=user, status='Accepted').values_list('friend_id', flat=True)
            # Get friends where user received and status is accepted
            friends_received = Friendship.objects.filter(friend=user, status='Accepted').values_list('user_id', flat=True)
            friend_ids = list(friends_initiated) + list(friends_received)
            self.fields['split_with'].queryset = User.objects.filter(id__in=friend_ids)
            self.fields['group'].queryset = ExpenseGroup.objects.filter(members=user)