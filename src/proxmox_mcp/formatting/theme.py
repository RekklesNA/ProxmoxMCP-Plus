"""
Theme configuration for Proxmox MCP output styling.
"""

class ProxmoxTheme:
    """Theme configuration for Proxmox MCP output."""
    
    # Feature flags
    USE_EMOJI = True
    USE_COLORS = True
    
    # ASCII status indicators for clients that do not handle emoji consistently.
    STATUS = {
        'online': '[online]',
        'offline': '[offline]',
        'running': '[running]',
        'stopped': '[stopped]',
        'unknown': '[unknown]',
        'pending': '[pending]',
        'error': '[error]',
        'warning': '[warning]',
    }
    
    # Resource type indicators
    RESOURCES = {
        'node': '[node]',
        'vm': '[vm]',
        'container': '[ct]',
        'storage': '[storage]',
        'cpu': '[cpu]',
        'memory': '[memory]',
        'network': '[network]',
        'disk': '[disk]',
        'backup': '[backup]',
        'snapshot': '[snapshot]',
        'template': '[template]',
        'pool': '[pool]',
    }
    
    # Action and operation indicators
    ACTIONS = {
        'success': '[ok]',
        'error': '[error]',
        'warning': '[warning]',
        'info': '[info]',
        'command': '[cmd]',
        'start': '[start]',
        'stop': '[stop]',
        'restart': '[restart]',
        'delete': '[delete]',
        'edit': '[edit]',
        'create': '[create]',
        'migrate': '[migrate]',
        'clone': '[clone]',
        'lock': '[lock]',
        'unlock': '[unlock]',
    }
    
    # Section and grouping indicators
    SECTIONS = {
        'header': '[header]',
        'details': '[details]',
        'statistics': '[stats]',
        'configuration': '[config]',
        'logs': '[logs]',
        'tasks': '[tasks]',
        'users': '[users]',
        'permissions': '[permissions]',
    }
    
    # Measurement and metric indicators
    METRICS = {
        'percentage': '%',
        'temperature': '[temp]',
        'uptime': '[uptime]',
        'bandwidth': '[bandwidth]',
        'latency': '[latency]',
    }
    
    @classmethod
    def get_status_emoji(cls, status: str) -> str:
        """Get emoji for a status value with fallback."""
        status = status.lower()
        return cls.STATUS.get(status, cls.STATUS['unknown'])
    
    @classmethod
    def get_resource_emoji(cls, resource: str) -> str:
        """Get emoji for a resource type with fallback."""
        resource = resource.lower()
        return cls.RESOURCES.get(resource, '')
    
    @classmethod
    def get_action_emoji(cls, action: str) -> str:
        """Get emoji for an action with fallback."""
        action = action.lower()
        return cls.ACTIONS.get(action, cls.ACTIONS['info'])
    
    @classmethod
    def get_section_emoji(cls, section: str) -> str:
        """Get emoji for a section type with fallback."""
        section = section.lower()
        return cls.SECTIONS.get(section, cls.SECTIONS['details'])
