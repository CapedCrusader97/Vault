import calendar
from django.db import models
from django.contrib.auth.models import User

class SecurityProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    q1_answer = models.CharField(max_length=150)
    q2_answer = models.CharField(max_length=150)
    q3_answer = models.CharField(max_length=150)

    def __str__(self):
        return self.user.username

class MonthlyBudget(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    year = models.IntegerField()
    month = models.IntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        unique_together = ('user', 'year', 'month')

    def __str__(self):
        return f"{self.user.username} - {self.month}/{self.year}: ₹{self.amount}"

class ExpenseGroup(models.Model):
    name = models.CharField(max_length=150)
    members = models.ManyToManyField(User, related_name='expense_groups')
    created_by = models.ForeignKey(User, related_name='created_groups', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Expense(models.Model):
    EXPENSE_TYPES = (
        ('One-Time', 'One-Time Payment'),
        ('Subscription', 'Recurring Subscription'),
        ('Bill', 'Monthly Bill'),
    )
    STATUS_CHOICES = (
        ('Paid', 'Paid'),
        ('Pending', 'Pending'),
    )
    CATEGORY_CHOICES = (
        ('Housing', 'Housing'),
        ('Utilities', 'Utilities'),
        ('Grocery', 'Grocery'),
        ('Food', 'Food'),
        ('Transportation', 'Transportation'),
        ('Healthcare', 'Healthcare'),
        ('Entertainment', 'Entertainment'),
        ('Credit Card', 'Credit Card'),
        ('Other', 'Other'),
    )
    PAYMENT_METHODS = (
        ('Credit Card', 'Credit Card'),
        ('Debit Card', 'Debit Card'),
        ('Cash', 'Cash'),
        ('None', 'Not Applicable / Pending'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=150, help_text="Recipient or Service Name")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='Other')
    expense_type = models.CharField(max_length=20, choices=EXPENSE_TYPES, default='One-Time')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='None')
    is_autopay = models.BooleanField(default=False)
    is_cc_bill = models.BooleanField(default=False)
    
    # Splitwise Features
    is_shared = models.BooleanField(default=False)
    paid_by = models.ForeignKey(User, related_name='expenses_paid', null=True, blank=True, on_delete=models.SET_NULL)
    group = models.ForeignKey('ExpenseGroup', related_name='expenses', null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True, null=True, help_text="Any additional comments or notes")
    
    SPLIT_TYPES = (
        ('Equal', 'Equal Split'),
        ('Percentage', 'Percentage (%)'),
        ('Exact', 'Exact Amounts'),
    )
    split_type = models.CharField(max_length=20, choices=SPLIT_TYPES, default='Equal')

    year = models.IntegerField(default=2026)
    month = models.IntegerField(default=1)
    week = models.IntegerField(default=1)

    def save(self, *args, **kwargs):
        if self.due_date:
            self.year = self.due_date.year
            self.month = self.due_date.month
            
            # --- SUNDAY-START CALENDAR WEEK LOGIC ---
            # 1. Get the 1st day of the month
            first_of_month = self.due_date.replace(day=1)
            
            # 2. Get weekday of the 1st (Monday=0 ... Sunday=6)
            # Transform so Sunday=0, Monday=1, ..., Saturday=6
            first_weekday_sun_offset = (first_of_month.weekday() + 1) % 7
            
            # 3. Calculate week number
            # (Day + Offset - 1) // 7 + 1
            self.week = (self.due_date.day + first_weekday_sun_offset - 1) // 7 + 1
            # ----------------------------------------
            
        super(Expense, self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} - ₹{self.amount}"

class Friendship(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Accepted', 'Accepted'),
    )
    user = models.ForeignKey(User, related_name='friendships_initiated', on_delete=models.CASCADE)
    friend = models.ForeignKey(User, related_name='friendships_received', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'friend')

    def __str__(self):
        return f"{self.user.username} -> {self.friend.username} ({self.status})"

class SplitTransaction(models.Model):
    expense = models.ForeignKey(Expense, related_name='splits', on_delete=models.CASCADE)
    debtor = models.ForeignKey(User, related_name='debts', on_delete=models.CASCADE)
    creditor = models.ForeignKey(User, related_name='credits', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_settled = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.debtor.username} owes {self.creditor.username} ₹{self.amount}"

class Settlement(models.Model):
    payer = models.ForeignKey(User, related_name='settlements_paid', on_delete=models.CASCADE)
    payee = models.ForeignKey(User, related_name='settlements_received', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.payer.username} paid {self.payee.username} ₹{self.amount}"

class SavingsGoal(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='savings_goals')
    name = models.CharField(max_length=150)
    target_amount = models.DecimalField(max_digits=10, decimal_places=2)
    current_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    target_date = models.DateField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - ₹{self.current_amount}/₹{self.target_amount}"
    
    @property
    def progress_percentage(self):
        if self.target_amount == 0:
            return 0
        percentage = (self.current_amount / self.target_amount) * 100
        return min(round(percentage), 100)