from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('register/', views.register, name='register'),
    
    # Updated to use our new CustomLoginView from views.py
    path('login/', views.CustomLoginView.as_view(), name='login'),
    
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('forgot-password/security-questions/', views.security_questions, name='security_questions'),
    path('forgot-password/reset/', views.reset_forgotten_password, name='reset_forgotten_password'),
    
    path('admin-users/', views.admin_users, name='admin_users'),
    
    path('add/', views.add_expense, name='add_expense'),
    path('edit/<int:pk>/', views.edit_expense, name='edit_expense'),
    path('delete/<int:pk>/', views.delete_expense, name='delete_expense'),
    path('profile/', views.profile, name='profile'),
    path('profile/change-password/', views.change_password, name='change_password'),
    path('profile/delete-account/', views.delete_account, name='delete_account'),
    path('friends/', views.friends_dashboard, name='friends_dashboard'),
    path('settle/<int:friend_id>/', views.settle_up, name='settle_up'),
    path('settle-split/<int:split_id>/', views.settle_split, name='settle_split'),
    
    path('export-csv/', views.export_csv_view, name='export_csv'),
    path('groups/', views.groups_dashboard, name='groups_dashboard'),
    path('groups/create/', views.create_group, name='create_group'),
    path('groups/<int:pk>/', views.group_detail, name='group_detail'),
    path('groups/<int:pk>/delete/', views.delete_group, name='delete_group'),
    
    path('goals/create/', views.create_goal, name='create_goal'),
    path('goals/<int:pk>/add-funds/', views.add_goal_funds, name='add_goal_funds'),
]