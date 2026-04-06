import datetime
import calendar
import csv
import logging
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.contrib import messages
from django.db.models import Sum, Q
from .models import Expense, SecurityProfile, MonthlyBudget, Friendship, SplitTransaction, Settlement, ExpenseGroup, SavingsGoal
from .forms import ExpenseForm, CustomRegistrationForm, CustomLoginForm, AddFriendForm, GroupForm, GoalForm, AddFundsForm

# --- CUSTOM LOGIN ROUTING ---
class CustomLoginView(LoginView):
    template_name = 'Vault/login.html'
    authentication_form = CustomLoginForm
    def get_success_url(self):
        if self.request.user.is_superuser:
            return reverse_lazy('admin_users')
        return reverse_lazy('dashboard')

# --- HELPER: CREDIT CARD AUTOMATION ---
def update_cc_bill(user, target_date):
    month = target_date.month
    year = target_date.year
    cc_total = Expense.objects.filter(
        user=user, payment_method='Credit Card', is_cc_bill=False, year=year, month=month
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year
    due_date = datetime.date(next_year, next_month, 10)
    title = f"Credit Card Bill - {datetime.date(year, month, 1).strftime('%B %Y')}"
    if cc_total > 0:
        bill, created = Expense.objects.get_or_create(
            user=user, is_cc_bill=True, due_date=due_date,
            defaults={'title': title, 'amount': cc_total, 'category': 'Credit Card', 'expense_type': 'Bill', 'status': 'Pending', 'payment_method': 'Debit Card'}
        )
        if not created:
            bill.amount = cc_total
            bill.save()
    else:
        Expense.objects.filter(user=user, is_cc_bill=True, due_date=due_date).delete()

logger = logging.getLogger(__name__)

def process_splits(expense, request, split_users=None):
    group_members = []
    if expense.group:
        group_members = list(expense.group.members.all())
    elif split_users:
        group_members = list(split_users)
        group_members.append(expense.paid_by)
        
    # Remove duplicates, ensure paid_by is in the list
    unique_members = {m.id: m for m in group_members}
    if expense.paid_by.id not in unique_members:
        unique_members[expense.paid_by.id] = expense.paid_by
        
    members = list(unique_members.values())
    total_people = len(members)

    if total_people <= 1:
        logger.info(f"Expense {expense.id} has no valid split members. Skipping split calculation.")
        return

    split_type = expense.split_type

    logger.info(f"Processing '{split_type}' split for Expense {expense.id} (Total: {expense.amount}) among {total_people} users.")

    if split_type == 'Percentage':
        for member in members:
            # Expecting 'split_percent_<id>' from frontend
            pct_str = request.POST.get(f'split_percent_{member.id}', '0')
            try:
                pct = float(pct_str)
            except ValueError:
                pct = 0.0
            
            member_amount = round(float(expense.amount) * (pct / 100.0), 2)
            if member != expense.paid_by and member_amount > 0:
                SplitTransaction.objects.create(
                    expense=expense, debtor=member, creditor=expense.paid_by, amount=member_amount
                )
                logger.info(f"Split Created: {member.username} owes {expense.paid_by.username} ₹{member_amount} ({pct}%)")

    elif split_type == 'Exact':
        for member in members:
            # Expecting 'split_amount_<id>' from frontend
            amt_str = request.POST.get(f'split_amount_{member.id}', '0')
            try:
                member_amount = float(amt_str)
            except ValueError:
                member_amount = 0.0
                
            if member != expense.paid_by and member_amount > 0:
                SplitTransaction.objects.create(
                    expense=expense, debtor=member, creditor=expense.paid_by, amount=member_amount
                )
                logger.info(f"Split Created: {member.username} owes {expense.paid_by.username} ₹{member_amount} (Exact)")

    else:
        # Accurate Equal Split with remainder handling
        base_split = round(float(expense.amount) / total_people, 2)
        total_assigned = base_split * total_people
        difference = round(float(expense.amount) - total_assigned, 2)
        
        for i, member in enumerate(members):
            amount_to_pay = base_split
            if i == 0:  # Assign difference to the first person
                amount_to_pay += difference
                
            amount_to_pay = round(amount_to_pay, 2)
            
            if member != expense.paid_by and amount_to_pay > 0:
                SplitTransaction.objects.create(
                    expense=expense, debtor=member, creditor=expense.paid_by, amount=amount_to_pay
                )
                logger.info(f"Split Created: {member.username} owes {expense.paid_by.username} ₹{amount_to_pay} (Equal)")

# --- AUTHENTICATION VIEWS ---
def register(request):
    if request.method == 'POST':
        form = CustomRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = CustomRegistrationForm()
    return render(request, 'Vault/register.html', {'form': form})

def forgot_password(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        user = User.objects.filter(username=username).first()
        if user:
            request.session['reset_user_id'] = user.id
            return redirect('security_questions')
        else:
            messages.error(request, "This user doesn't exist.")
    return render(request, 'Vault/forgot_password.html')

def security_questions(request):
    user_id = request.session.get('reset_user_id')
    if not user_id: return redirect('forgot_password')
    user = get_object_or_404(User, id=user_id)
    profile = get_object_or_404(SecurityProfile, user=user)
    if request.method == 'POST':
        ans1, ans2, ans3 = request.POST.get('q1').strip().lower(), request.POST.get('q2').strip().lower(), request.POST.get('q3').strip().lower()
        if ans1 == profile.q1_answer and ans2 == profile.q2_answer and ans3 == profile.q3_answer:
            request.session['can_reset_password'] = True
            return redirect('reset_forgotten_password')
        else: messages.error(request, "One or more answers are incorrect.")
    return render(request, 'Vault/security_questions.html')

def reset_forgotten_password(request):
    if not request.session.get('can_reset_password'): return redirect('forgot_password')
    user = get_object_or_404(User, id=request.session.get('reset_user_id'))
    if request.method == 'POST':
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            request.session.pop('reset_user_id', None); request.session.pop('can_reset_password', None)
            messages.success(request, "Password successfully reset!")
            return redirect('login')
    else: form = SetPasswordForm(user)
    return render(request, 'Vault/reset_forgotten_password.html', {'form': form})

# --- ADMIN VIEW ---
@user_passes_test(lambda u: u.is_superuser)
def admin_users(request):
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'Vault/admin_users.html', {'users': users})

# --- DASHBOARD ---
@login_required
def dashboard(request):
    if request.user.is_superuser: return redirect('admin_users')
    today = datetime.date.today()
    current_year = today.year
    available_years = [current_year - 2, current_year - 1, current_year]
    selected_year = int(request.GET.get('year', current_year))
    selected_month = int(request.GET.get('month', today.month))
    selected_week = request.GET.get('week', '')
    query = request.GET.get('q', '')

    if request.method == "POST" and "set_budget" in request.POST:
        budget_val = request.POST.get("budget_amount", 0)
        MonthlyBudget.objects.update_or_create(user=request.user, year=selected_year, month=selected_month, defaults={'amount': budget_val})
        return redirect(f"{request.path}?year={selected_year}&month={selected_month}")

    budget_obj = MonthlyBudget.objects.filter(user=request.user, year=selected_year, month=selected_month).first()
    monthly_budget = float(budget_obj.amount) if budget_obj else 0.0

    expenses = Expense.objects.filter(user=request.user, year=selected_year, month=selected_month).order_by('due_date')
    if selected_week: expenses = expenses.filter(week=int(selected_week))
    if query: expenses = expenses.filter(title__icontains=query)

    # Add virtual expenses for all splits (settled and unsettled)
    all_splits = SplitTransaction.objects.filter(debtor=request.user).select_related('expense', 'creditor')
    virtual_expenses = []
    for split in all_splits:
        if split.expense.year == selected_year and split.expense.month == selected_month:
            if selected_week:
                # Calculate week for virtual
                import calendar
                first_of_month = split.expense.due_date.replace(day=1)
                first_weekday_sun_offset = (first_of_month.weekday() + 1) % 7
                week = (split.expense.due_date.day + first_weekday_sun_offset - 1) // 7 + 1
                if week != int(selected_week):
                    continue
            if query and query.lower() not in split.expense.title.lower():
                continue
            virtual_expenses.append({
                'id': f'split_{split.id}',
                'title': f'Owed to {split.creditor.username} for {split.expense.title}',
                'amount': split.amount,
                'due_date': split.expense.due_date,
                'category': split.expense.category,
                'expense_type': 'Shared',
                'status': 'Paid' if split.is_settled else 'Pending',
                'payment_method': 'Debit Card' if split.is_settled else 'Owed',
                'is_autopay': False,
                'is_shared': True,
                'is_virtual': True,
                'split': split,
            })

    # Combine and sort
    combined_expenses = list(expenses) + virtual_expenses
    combined_expenses.sort(key=lambda x: x['due_date'] if isinstance(x, dict) else x.due_date)

    cash_outflow = expenses.filter(status='Paid').exclude(payment_method='Credit Card').aggregate(Sum('amount'))['amount__sum'] or 0
    cc_spend = expenses.filter(payment_method='Credit Card').exclude(is_cc_bill=True).aggregate(Sum('amount'))['amount__sum'] or 0
    total_spent_this_month = float(cash_outflow) + float(cc_spend)
    
    budget_remaining = monthly_budget - total_spent_this_month
    is_over_budget = total_spent_this_month > monthly_budget
    
    pending_bills = []
    for e in combined_expenses:
        if isinstance(e, dict):
            if e.get('status') == 'Pending' and e.get('payment_method') != 'Credit Card':
                pending_bills.append(e)
        else:  # Expense object
            if e.status == 'Pending' and e.payment_method != 'Credit Card':
                pending_bills.append({'amount': e.amount})
    pending_amount = sum(float(e['amount']) for e in pending_bills)
    projected_burn = float(pending_amount)

    cat_data = expenses.filter(status='Paid', is_cc_bill=False).values('category').annotate(total=Sum('amount')).order_by('category')
    chart_labels = [item['category'] for item in cat_data]; chart_data = [float(item['total']) for item in cat_data]
    cc_bill_paid = expenses.filter(status='Paid', is_cc_bill=True).aggregate(Sum('amount'))['amount__sum'] or 0
    
    unpaid_cat_data = expenses.filter(status='Pending', is_cc_bill=False).values('category').annotate(total=Sum('amount')).order_by('category')
    unpaid_chart_labels = [item['category'] for item in unpaid_cat_data]; unpaid_chart_data = [float(item['total']) for item in unpaid_cat_data]
    cc_bill_pending = expenses.filter(status='Pending', is_cc_bill=True).aggregate(Sum('amount'))['amount__sum'] or 0
    
    method_data = expenses.filter(status='Paid').exclude(payment_method='None').values('payment_method').annotate(total=Sum('amount')).order_by('payment_method')
    method_chart_labels = [item['payment_method'] for item in method_data]; method_chart_data = [float(item['total']) for item in method_data]
    autopay_data = expenses.filter(is_autopay=True).values('category').annotate(total=Sum('amount')).order_by('category')
    autopay_chart_labels = [item['category'] for item in autopay_data]; autopay_chart_data = [float(item['total']) for item in autopay_data]
    autopay_chart_labels = [item['category'] for item in autopay_data]; autopay_chart_data = [float(item['total']) for item in autopay_data]

    # Add virtual expenses to charts and KPIs
    virtual_paid = [e for e in virtual_expenses if e['status'] == 'Paid']
    virtual_pending = [e for e in virtual_expenses if e['status'] == 'Pending']

    # Update KPIs with virtual expenses
    virtual_paid_total = sum(float(e['amount']) for e in virtual_paid)
    
    cash_outflow = float(cash_outflow) + virtual_paid_total
    total_spent_this_month = float(total_spent_this_month) + virtual_paid_total
    budget_remaining = monthly_budget - total_spent_this_month
    is_over_budget = total_spent_this_month > monthly_budget
    projected_burn = float(cash_outflow) + float(pending_amount)

    # Merge paid category data with CC bills
    virtual_cat_totals = {}
    for e in virtual_paid:
        cat = e['category']
        virtual_cat_totals[cat] = virtual_cat_totals.get(cat, 0) + float(e['amount'])
    merged_cat_data = {item['category']: float(item['total']) for item in cat_data}
    for cat, amt in virtual_cat_totals.items():
        merged_cat_data[cat] = merged_cat_data.get(cat, 0) + amt
    if float(cc_bill_paid) > 0:
        merged_cat_data['Credit Card Bill'] = float(cc_bill_paid)
    chart_labels = list(merged_cat_data.keys())
    chart_data = list(merged_cat_data.values())

    # Merge unpaid category data with CC bills
    virtual_unpaid_totals = {}
    for e in virtual_pending:
        cat = e['category']
        virtual_unpaid_totals[cat] = virtual_unpaid_totals.get(cat, 0) + float(e['amount'])
    merged_unpaid = {item['category']: float(item['total']) for item in unpaid_cat_data}
    for cat, amt in virtual_unpaid_totals.items():
        merged_unpaid[cat] = merged_unpaid.get(cat, 0) + amt
    if float(cc_bill_pending) > 0:
        merged_unpaid['Credit Card Bill'] = float(cc_bill_pending)
    unpaid_chart_labels = list(merged_unpaid.keys())
    unpaid_chart_data = list(merged_unpaid.values())

    # Merge method data (only paid with Debit Card for virtual)
    if virtual_paid_total > 0:
        merged_method = {item['payment_method']: float(item['total']) for item in method_data}
        merged_method['Debit Card'] = merged_method.get('Debit Card', 0) + virtual_paid_total
        method_chart_labels = list(merged_method.keys())
        method_chart_data = list(merged_method.values())
    
    # Ensure SavingsGoal is fetched (including completed ones to show achievements)
    active_goals = SavingsGoal.objects.filter(user=request.user).order_by('target_date')

    # Calculate Smart Insights
    insights = []

    # 1. Budget approaching handling
    if monthly_budget > 0:
        budget_pct = total_spent_this_month / monthly_budget
        if budget_pct >= 0.8 and budget_pct <= 1.0:
            insights.append({'type': 'warning', 'message': f'You have spent {int(budget_pct*100)}% of your budget. Slow down!'})
        elif budget_pct > 1.0:
            insights.append({'type': 'danger', 'message': f'You are over budget by ₹{(total_spent_this_month - monthly_budget):.2f}.'})
    
    # 2. Upcoming bills in next 7 days
    upcoming_bills = expenses.filter(status='Pending', due_date__range=[today, today + datetime.timedelta(days=7)])
    if upcoming_bills.exists():
        total_upcoming = upcoming_bills.aggregate(Sum('amount'))['amount__sum'] or 0
        insights.append({'type': 'info', 'message': f'You have {upcoming_bills.count()} pending bills due inside 7 days totaling ₹{total_upcoming:.2f}.'})
        
    # 3. Monthly subscription burn rate
    subs = Expense.objects.filter(user=request.user, expense_type='Subscription')
    if subs.exists():
        monthly_burn = subs.aggregate(Sum('amount'))['amount__sum'] or 0
        insights.append({'type': 'tip', 'message': f'Your total active subscription baseline is ₹{monthly_burn:.2f}. Review to save money.'})

    if not insights:
        insights.append({'type': 'success', 'message': 'Your finances are neatly organized. Keep going!'})

    context = {
        'expenses': combined_expenses, 'cash_outflow': cash_outflow, 'cc_spend': cc_spend, 'projected_burn': projected_burn,
        'query': query, 'available_years': available_years, 'selected_year': selected_year, 'selected_month': selected_month, 'selected_week': selected_week,
        'chart_labels': chart_labels, 'chart_data': chart_data, 'unpaid_chart_labels': unpaid_chart_labels, 'unpaid_chart_data': unpaid_chart_data,
        'method_chart_labels': method_chart_labels, 'method_chart_data': method_chart_data, 'autopay_chart_labels': autopay_chart_labels, 'autopay_chart_data': autopay_chart_data,
        'monthly_budget': monthly_budget, 'total_spent_this_month': total_spent_this_month, 'budget_remaining': abs(budget_remaining), 'is_over_budget': is_over_budget, 'has_budget': monthly_budget > 0,
        'active_goals': active_goals, 'insights': insights,
    }
    return render(request, 'Vault/dashboard.html', context)

# --- CRUD ACTIONS (STAY ON FILTERED DATE) ---
@login_required
def add_expense(request):
    group_id = request.GET.get('group')
    initial = {}
    if group_id:
        initial['group'] = group_id

    friends_initiated = Friendship.objects.filter(user=request.user, status='Accepted').values_list('friend_id', flat=True)
    friends_received = Friendship.objects.filter(friend=request.user, status='Accepted').values_list('user_id', flat=True)
    friend_ids = list(friends_initiated) + list(friends_received)

    if request.method == 'POST':
        form = ExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = request.user
            expense.paid_by = request.user
            expense.save() 
            update_cc_bill(request.user, expense.due_date)
            
            logger.info(f"Created new Expense: {expense.id} by User: {request.user.username}")

            # Split logic improvement
            if expense.group:
                expense.is_shared = True
                expense.save()
                process_splits(expense, request)
            elif expense.is_shared:
                split_users = form.cleaned_data.get('split_with')
                if split_users:
                    process_splits(expense, request, split_users)

            # Stay on the year/month of the record added
            r_year, r_month = expense.due_date.year, expense.due_date.month

            if expense.expense_type == 'Subscription':
                original_max_days = calendar.monthrange(expense.due_date.year, expense.due_date.month)[1]
                is_end_of_month = (expense.due_date.day == original_max_days)
                for future_month in range(expense.due_date.month + 1, 13):
                    f_max = calendar.monthrange(expense.due_date.year, future_month)[1]
                    f_day = f_max if is_end_of_month else min(expense.due_date.day, f_max)
                    f_date = datetime.date(expense.due_date.year, future_month, f_day)
                    Expense.objects.create(user=expense.user, title=expense.title, amount=expense.amount, due_date=f_date, category=expense.category, expense_type='Subscription', status='Pending', payment_method=expense.payment_method, is_autopay=expense.is_autopay)
                    update_cc_bill(expense.user, f_date)
            
            if expense.group:
                return redirect('group_detail', pk=expense.group.pk)
            return redirect(f'/?year={r_year}&month={r_month}')
    else: form = ExpenseForm(user=request.user, initial=initial)
    
    import json
    groups_data = {}
    for g in request.user.expense_groups.all():
        groups_data[g.id] = [{'id': m.id, 'username': m.username} for m in g.members.all()]
        
    friends_queryset = User.objects.filter(id__in=friend_ids)
    friends_data = [{'id': f.id, 'username': f.username} for f in friends_queryset]
        
    return render(request, 'Vault/expense_form.html', {
        'form': form, 
        'action': 'Add',
        'groups_data': json.dumps(groups_data),
        'friends_data': json.dumps(friends_data),
        'current_user': json.dumps({'id': request.user.id, 'username': request.user.username})
    })

@login_required
def edit_expense(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)

    friends_initiated = Friendship.objects.filter(user=request.user, status='Accepted').values_list('friend_id', flat=True)
    friends_received = Friendship.objects.filter(friend=request.user, status='Accepted').values_list('user_id', flat=True)
    friend_ids = list(friends_initiated) + list(friends_received)

    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense, user=request.user)
        if form.is_valid():
            saved_expense = form.save()
            update_cc_bill(request.user, saved_expense.due_date)
            
            logger.info(f"Updated Expense: {saved_expense.id} by User: {request.user.username}")
            
            if saved_expense.group:
                SplitTransaction.objects.filter(expense=saved_expense).delete()
                saved_expense.is_shared = True
                saved_expense.save()
                process_splits(saved_expense, request)
            elif saved_expense.is_shared:
                SplitTransaction.objects.filter(expense=saved_expense).delete()
                split_users = form.cleaned_data.get('split_with')
                if split_users:
                    process_splits(saved_expense, request, split_users)
                        
            if saved_expense.group:
                return redirect('group_detail', pk=saved_expense.group.pk)
            return redirect(f'/?year={saved_expense.due_date.year}&month={saved_expense.due_date.month}')
    else: form = ExpenseForm(instance=expense, user=request.user)
    
    # Pre-fill split_with for edit
    if expense.is_shared and not expense.group:
        split_users = list(set(split.debtor for split in expense.splits.all()))
        form.fields['split_with'].initial = split_users

    import json
    groups_data = {}
    for g in request.user.expense_groups.all():
        groups_data[g.id] = [{'id': m.id, 'username': m.username} for m in g.members.all()]

    friends_queryset = User.objects.filter(id__in=friend_ids)
    friends_data = [{'id': f.id, 'username': f.username} for f in friends_queryset]

    # Existing splits data for pre-filling amounts
    existing_splits = {}
    if expense.is_shared:
        for split in expense.splits.all():
            if expense.split_type == 'Percentage':
                pct = (split.amount / expense.amount) * 100 if expense.amount > 0 else 0
                existing_splits[split.debtor.id] = float(pct)
            else:  # Exact or Equal
                existing_splits[split.debtor.id] = float(split.amount)

    return render(request, 'Vault/expense_form.html', {
        'form': form, 
        'action': 'Edit',
        'groups_data': json.dumps(groups_data),
        'friends_data': json.dumps(friends_data),
        'existing_splits': json.dumps(existing_splits),
        'current_user': json.dumps({'id': request.user.id, 'username': request.user.username})
    })

@login_required
def delete_expense(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    # Store date before deleting to use for redirect
    r_year, r_month = expense.due_date.year, expense.due_date.month
    if request.method == 'POST':
        target_date = expense.due_date; expense_id = expense.id; expense.delete(); update_cc_bill(request.user, target_date)
        logger.info(f"Deleted Expense: {expense_id} by User: {request.user.username}")
        return redirect(f'/?year={r_year}&month={r_month}')
    return render(request, 'Vault/confirm_delete.html', {'expense': expense})

# --- USER PROFILE & ACCOUNT SETTINGS ---
@login_required
def profile(request):
    if request.user.is_superuser: return redirect('admin_users')
    total_records = Expense.objects.filter(user=request.user).count()
    total_autopay = Expense.objects.filter(user=request.user, is_autopay=True).count()
    return render(request, 'Vault/profile.html', {'total_records': total_records, 'total_autopay': total_autopay})

@login_required
def change_password(request):
    if request.user.is_superuser: return redirect('admin_users')
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save(); update_session_auth_hash(request, user)
            return redirect('profile')
    else: form = PasswordChangeForm(request.user)
    return render(request, 'Vault/change_password.html', {'form': form})

@login_required
def delete_account(request):
    if request.user.is_superuser: return redirect('admin_users')
    if request.method == 'POST':
        request.user.delete()
        return redirect('login')
    return render(request, 'Vault/delete_account.html')

# --- FRIENDS & SPLITTING ---
@login_required
def friends_dashboard(request):
    if request.user.is_superuser: return redirect('admin_users')
    
    if request.method == 'POST' and 'add_friend' in request.POST:
        friend_form = AddFriendForm(request.POST)
        if friend_form.is_valid():
            username = friend_form.cleaned_data['username']
            try:
                friend_user = User.objects.get(username=username)
                if friend_user != request.user:
                    Friendship.objects.get_or_create(user=request.user, friend=friend_user)
                    messages.success(request, f"Friend request sent to {username}")
                else:
                    messages.error(request, "You cannot add yourself.")
            except User.DoesNotExist:
                messages.error(request, "User not found.")
        return redirect('friends_dashboard')

    if request.method == 'POST' and 'accept_friend' in request.POST:
        friendship_id = request.POST.get('friendship_id')
        try:
            f = Friendship.objects.get(id=friendship_id, friend=request.user, status='Pending')
            f.status = 'Accepted'
            f.save()
            messages.success(request, f"You are now friends with {f.user.username}")
        except Friendship.DoesNotExist:
            pass
        return redirect('friends_dashboard')

    if request.method == 'POST' and 'decline_friend' in request.POST:
        friendship_id = request.POST.get('friendship_id')
        try:
            f = Friendship.objects.get(id=friendship_id, friend=request.user, status='Pending')
            f.delete()
            messages.info(request, f"Declined friend request from {f.user.username}")
        except Friendship.DoesNotExist:
            pass
        return redirect('friends_dashboard')

    if request.method == 'POST' and 'remove_friend' in request.POST:
        friend_id = request.POST.get('friend_id')
        try:
            friend = User.objects.get(id=friend_id)
            # Delete friendships
            Friendship.objects.filter(
                (Q(user=request.user, friend=friend) | Q(user=friend, friend=request.user))
            ).delete()
            # Mark all splits as settled
            SplitTransaction.objects.filter(
                (Q(creditor=request.user, debtor=friend) | Q(creditor=friend, debtor=request.user)),
                is_settled=False
            ).update(is_settled=True)
            messages.success(request, f"Removed {friend.username} from friends. All pending debts settled.")
        except User.DoesNotExist:
            pass
        return redirect('friends_dashboard')
        
    friend_form = AddFriendForm()
    pending_requests = Friendship.objects.filter(friend=request.user, status='Pending')
    
    friends = set()
    for f in Friendship.objects.filter(user=request.user, status='Accepted'): friends.add(f.friend)
    for f in Friendship.objects.filter(friend=request.user, status='Accepted'): friends.add(f.user)
    
    balances = []
    for f in friends:
        owed_to_me = sum(s.amount for s in SplitTransaction.objects.filter(creditor=request.user, debtor=f, is_settled=False))
        i_owe = sum(s.amount for s in SplitTransaction.objects.filter(creditor=f, debtor=request.user, is_settled=False))
        
        net_balance = owed_to_me - i_owe
        
        balances.append({'friend': f, 'balance': net_balance, 'id': f.id})
        
    pending_splits = SplitTransaction.objects.filter(debtor=request.user, is_settled=False).select_related('expense', 'creditor')
        
    return render(request, 'Vault/friends.html', {
        'friend_form': friend_form, 
        'pending_requests': pending_requests,
        'balances': balances,
        'pending_splits': pending_splits
    })

@login_required
def settle_split(request, split_id):
    if request.method == 'POST':
        split = get_object_or_404(SplitTransaction, id=split_id, debtor=request.user, is_settled=False)
        Settlement.objects.create(payer=request.user, payee=split.creditor, amount=split.amount)
        split.is_settled = True
        split.save()
        logger.info(f"Split settled: User {request.user.username} paid {split.creditor.username} ₹{split.amount}")
        messages.success(request, f"You paid {split.creditor.username} ₹{split.amount}")
        return redirect('friends_dashboard')
    return redirect('friends_dashboard')

@login_required
def settle_up(request, friend_id):
    if request.method == 'POST':
        friend = get_object_or_404(User, id=friend_id)
        # Settle what I owe to the friend
        splits = SplitTransaction.objects.filter(creditor=friend, debtor=request.user, is_settled=False)
        total_debt = sum(s.amount for s in splits)
        if total_debt > 0:
            Settlement.objects.create(payer=request.user, payee=friend, amount=total_debt)
            splits.update(is_settled=True)
            logger.info(f"Settlement: User {request.user.username} settled ₹{total_debt} with {friend.username}")
            messages.success(request, f"You settled your debt with {friend.username}")
        return redirect('friends_dashboard')
    return redirect('friends_dashboard')

# --- EXPORT ---
@login_required
def export_csv_view(request):
    year = request.GET.get('year')
    month = request.GET.get('month')
    
    expenses = Expense.objects.filter(user=request.user).order_by('-due_date')
    if year: expenses = expenses.filter(year=int(year))
    if month: expenses = expenses.filter(month=int(month))
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="expenses_{year or "all"}_{month or "all"}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Title', 'Category', 'Amount', 'Status', 'Payment Method', 'Shared', 'Group', 'Split Type', 'Notes'])
    
    for e in expenses:
        group_name = e.group.name if e.group else ''
        writer.writerow([e.due_date, e.title, e.category, e.amount, e.status, e.payment_method, e.is_shared, group_name, e.split_type, e.notes or ''])
        
    return response

# --- GROUPS ---
@login_required
def groups_dashboard(request):
    if request.user.is_superuser: return redirect('admin_users')
    
    # Get groups where user is a member
    groups = request.user.expense_groups.all()
    
    return render(request, 'Vault/groups.html', {'groups': groups})

@login_required
def create_group(request):
    if request.user.is_superuser: return redirect('admin_users')
    
    if request.method == 'POST':
        form = GroupForm(request.POST, user=request.user)
        if form.is_valid():
            group = form.save(commit=False)
            group.created_by = request.user
            group.save()
            form.save_m2m() # Save members
            # Ensure creator is in the group
            group.members.add(request.user)
            messages.success(request, f"Group '{group.name}' created.")
            return redirect('groups_dashboard')
    else:
        form = GroupForm(user=request.user)
        
    return render(request, 'Vault/create_group.html', {'form': form})

@login_required
def group_detail(request, pk):
    if request.user.is_superuser: return redirect('admin_users')
    
    group = get_object_or_404(ExpenseGroup, pk=pk, members=request.user)
    expenses = group.expenses.all().order_by('-due_date')
    
    # Calculate simple group balances
    members = group.members.all()
    balances = []
    
    for f in members:
        if f == request.user: continue
        # Owed to me from this friend FOR group expenses
        owed_to_me = sum(s.amount for s in SplitTransaction.objects.filter(creditor=request.user, debtor=f, expense__group=group, is_settled=False))
        # I owe this friend FOR group expenses
        i_owe = sum(s.amount for s in SplitTransaction.objects.filter(creditor=f, debtor=request.user, expense__group=group, is_settled=False))
        net_balance = owed_to_me - i_owe
        balances.append({'friend': f, 'balance': net_balance, 'abs_balance': abs(net_balance)})
        
    return render(request, 'Vault/group_detail.html', {'group': group, 'expenses': expenses, 'balances': balances})

@login_required
def delete_group(request, pk):
    if request.user.is_superuser: return redirect('admin_users')
    group = get_object_or_404(ExpenseGroup, pk=pk, members=request.user)
    if request.method == 'POST':
        group_name = group.name
        group.delete()
        messages.success(request, f"Group '{group_name}' was successfully deleted.")
        return redirect('groups_dashboard')
    return redirect('groups_dashboard')

# --- GOALS ---
@login_required
def create_goal(request):
    if request.user.is_superuser: return redirect('admin_users')
    if request.method == 'POST':
        form = GoalForm(request.POST)
        if form.is_valid():
            goal = form.save(commit=False)
            goal.user = request.user
            goal.save()
            messages.success(request, f"Savings Goal '{goal.name}' created!")
            return redirect('dashboard')
    else:
        form = GoalForm()
    return render(request, 'Vault/create_goal.html', {'form': form})

@login_required
def add_goal_funds(request, pk):
    goal = get_object_or_404(SavingsGoal, pk=pk, user=request.user)
    if request.method == 'POST':
        form = AddFundsForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            goal.current_amount += amount
            if goal.current_amount >= goal.target_amount:
                goal.is_completed = True
            goal.save()
            messages.success(request, f"Added ₹{amount} to {goal.name}!")
            return redirect('dashboard')
    else:
        form = AddFundsForm()
    return render(request, 'Vault/add_funds.html', {'form': form, 'goal': goal})