# Revert Documentation: Fix `review_count` & `badge_list` property errors

## Problem

`AttributeError: property 'review_count' of 'Agent' object has no setter`
`AttributeError: property 'badge_list' of 'Agent' object has no setter`

**Root cause:** `Agent` model (`apps/agents/models.py`) defines `review_count` (line 177) and `badge_list` (line 396) as `@property` read-only descriptors. The admin view was assigning to these properties via queryset annotation conflict and direct assignment.

## Changes Made (4 files created/edited)

### 1. New file: `apps/admin_panel/views/agents.py`
- Created `agent_list` view function
- Uses annotation `_total_reviews` instead of `review_count` to avoid property conflict
- Assigns badge data to `agent._badges` instead of `agent.badge_list` to avoid property conflict
- Supports search by name, email, mobile, pincode
- Paginates results (20 per page)

### 2. Modified: `apps/admin_panel/views/__init__.py`
- Added `agents` to the import statement

### 3. Modified: `apps/admin_panel/urls.py`
- Added `agents` to the import from `.views`
- Added route: `path('agents/', agents.agent_list, name='agent_list')`

### 4. New file: `templates/admin/agents_list.html`
- Admin template extending `admin/layout.html`
- Search form, agent table with ID, Name, Email, Mobile, Pincode, Status, Plan, Reviews (`_total_reviews`), Badges (`_badges`), Actions
- Pagination

## How to Revert

### Option A: Revert all changes (remove agents view entirely)

1. **Delete the view file:**
   ```powershell
   Remove-Item -LiteralPath "apps/admin_panel/views/agents.py"
   ```

2. **Restore `views/__init__.py`:**
   Remove `agents,` from the import line:
   ```python
   from . import advanced, auth, broadcast, contacts, content, dashboard, export, finance, notify, reviews, settings, subscriptions, security, pincode, geocoding
   ```

3. **Restore `urls.py`:**
   - Remove `agents,` from the import line
   - Remove the route block:
     ```python
     # Agents
     path('agents/',                 agents.agent_list,   name='agent_list'),
     ```

4. **Delete the template:**
   ```powershell
   Remove-Item -LiteralPath "templates/admin/agents_list.html"
   ```

### Option B: Revert individual files

- Each file listed above can be individually restored by reversing the exact changes shown.

## Files NOT modified

The following files remain completely untouched:
- `apps/agents/models.py` — Agent model properties unchanged
- `apps/admin_panel/decorators.py` — unchanged
- All other views, templates, and app logic — unchanged
