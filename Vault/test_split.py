import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finance_tracking_app.settings')
django.setup()

from Vault.models import *
from django.contrib.auth.models import User

# Print all SplitTransactions
print("Splits:")
for s in SplitTransaction.objects.all():
    print(f"Expense {s.expense.title}: {s.debtor.username} owes {s.creditor.username} {s.amount}")
    
# Print group balances logic test
print("\nGroup balances:")
groups = ExpenseGroup.objects.all()
for group in groups:
    print(f"Group: {group.name}")
    for request_user in group.members.all():
        print(f"  User {request_user.username} sees:")
        for f in group.members.all():
            if f == request_user: continue
            owed_to_me = sum(s.amount for s in SplitTransaction.objects.filter(creditor=request_user, debtor=f, expense__group=group, is_settled=False))
            i_owe = sum(s.amount for s in SplitTransaction.objects.filter(creditor=f, debtor=request_user, expense__group=group, is_settled=False))
            net_balance = owed_to_me - i_owe
            print(f"    vs {f.username}: owed_to_me={owed_to_me}, i_owe={i_owe}, net={net_balance}")
