"""
RBAC Service for enforcing Role-Based Access Control
Handles project and page-level access validation
"""

from django.contrib.auth.models import User


class RBACService:
    """Service for RBAC operations"""
    
    @staticmethod
    def has_project_access(user: User, project_id: int) -> bool:
        """
        Check if user has access to a specific project.
        ENFORCES RBAC FOR EVERYONE - NO SUPERUSER BYPASS
        
        Args:
            user: Django User object
            project_id: ID of the project to check access for
            
        Returns:
            bool: True if user has access, False otherwise
        """
        if not user.is_authenticated:
            return False
        
        try:
            user_profile = user.profile
            user_group = user_profile.group
            
            # print(f"[RBAC] Checking access for user {user.username}, group: {user_group}")
            
            if not user_group:
                # print(f"[RBAC] User {user.username} has no group assigned")
                return False
            
            from dashboard.models import GroupAccess
            
            group_access = GroupAccess.objects.filter(group=user_group).first()
            if not group_access:
                # print(f"[RBAC] No GroupAccess found for group {user_group}")
                return False
            
            # Check if project is in the group's accessible projects
            has_access = group_access.projects.filter(id=project_id).exists()
            # print(f"[RBAC] Group {user_group.name} has access to project {project_id}: {has_access}")
            
            if has_access:
                project = group_access.projects.get(id=project_id)
                # print(f"[RBAC] Accessible project: {project.name}")
            
            return has_access
        
        except Exception as e:
            print(f"[RBAC ERROR] Error checking project access: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    @staticmethod
    def has_page_access(user: User, project_id: int, page_code: str) -> bool:
        """
        Check if user has access to a specific page within a project.
        
        Args:
            user: Django User object
            project_id: ID of the project
            page_code: Code of the page to check access for
            
        Returns:
            bool: True if user has access to both project and page, False otherwise
        """
        if not user.is_authenticated:
            return False
        
        # Superusers always have access
        if user.is_superuser:
            return True
        
        # First check if user has project access
        if not RBACService.has_project_access(user, project_id):
            return False
        
        try:
            user_profile = user.profile
            user_group = user_profile.group
            
            if not user_group:
                return False
            
            from dashboard.models import GroupAccess
            
            group_access = GroupAccess.objects.filter(group=user_group).first()
            if not group_access:
                return False
            
            # Check if page code is in the group's accessible pages
            return group_access.pages.filter(code=page_code).exists()
        
        except Exception as e:
            print(f"Error checking page access: {e}")
            return False
    
    @staticmethod
    def get_user_projects(user: User):
        """
        Get all projects accessible to a user.
        ENFORCES RBAC FOR EVERYONE - NO SUPERUSER BYPASS
        
        Args:
            user: Django User object
            
        Returns:
            QuerySet: Projects accessible to the user
        """
        if not user.is_authenticated:
            return None
        
        try:
            user_profile = user.profile
            user_group = user_profile.group
            
            if not user_group:
                return None
            
            from dashboard.models import GroupAccess
            
            group_access = GroupAccess.objects.filter(group=user_group).first()
            if not group_access:
                return None
            
            return group_access.projects.filter(is_active=True)
        
        except Exception as e:
            print(f"Error getting user projects: {e}")
            return None
    
    @staticmethod
    def get_user_page_codes(user: User):
        """
        Get all page codes accessible to a user.
        
        Args:
            user: Django User object
            
        Returns:
            set: Set of page codes accessible to the user
        """
        if not user.is_authenticated:
            return set()
        
        try:
            user_profile = user.profile
            user_group = user_profile.group
            
            if not user_group:
                return set()
            
            from dashboard.models import GroupAccess
            
            group_access = GroupAccess.objects.filter(group=user_group).first()
            if not group_access:
                return set()
            
            return set(group_access.pages.values_list('code', flat=True))
        
        except Exception as e:
            print(f"Error getting user page codes: {e}")
            return set()
    
    @staticmethod
    def can_access_project_url(user: User, project_code: str) -> bool:
        """
        Check if user can access a specific project by its code.
        Used to prevent URL-based access to unauthorized projects.
        
        Args:
            user: Django User object
            project_code: Project code from URL (e.g., 'ultratech', 'mbmt')
            
        Returns:
            bool: True if user can access the project, False otherwise
        """
        if not user.is_authenticated:
            # print(f"[RBAC] User not authenticated for project: {project_code}")
            return False
        
        try:
            from dashboard.models import Project
            from dashboard.project_routing import normalize_project_code
            
            # Normalize the code to uppercase (ULTRATECH, MBMT, etc.)
            normalized_code = normalize_project_code(project_code)
            if not normalized_code:
                # print(f"[RBAC] Failed to normalize project code: {project_code}")
                return False
            
            # print(f"[RBAC] Looking up project with name__iexact={normalized_code}")
            
            # Lookup project by name (comparing case-insensitive)
            # Project.name is "ULTRATECH", "MBMT", etc.
            project = Project.objects.filter(name__iexact=normalized_code).first()
            
            if not project:
                # print(f"[RBAC] Project not found with name: {normalized_code}")
                return False
            
            # print(f"[RBAC] Found project: {project.name} (id={project.id})")
            
            # Check if user has access to this project
            has_access = RBACService.has_project_access(user, project.id)
            # print(f"[RBAC] User {user.username} access to {project.name}: {has_access}")
            
            return has_access
        
        except Exception as e:
            print(f"[RBAC ERROR] Error checking project URL access: {e}")
            import traceback
            traceback.print_exc()
            return False
