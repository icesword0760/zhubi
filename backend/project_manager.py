"""
项目管理模块
管理标注项目的创建、删除、更新等操作
"""

import os
import json
import shutil
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote


_PROJECT_LOCKS = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


def shared_project_lock(project_path: str):
    """Return the process-wide lock for a canonical project path."""
    key = os.path.realpath(os.path.abspath(project_path))
    with _PROJECT_LOCKS_GUARD:
        return _PROJECT_LOCKS.setdefault(key, threading.RLock())


class ProjectManager:
    """项目管理器"""

    IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
    
    def __init__(self, projects_dir: str):
        os.makedirs(projects_dir, exist_ok=True)
        self.projects_dir = os.path.realpath(os.path.abspath(projects_dir))

    @staticmethod
    def _validate_path_id(value: str, label: str) -> None:
        """Require an identifier to be exactly one non-special path component."""
        if (
            not isinstance(value, str)
            or not value
            or value in ('.', '..')
            or '/' in value
            or '\\' in value
            or '\x00' in value
            or os.path.basename(value) != value
        ):
            raise ValueError(f"无效的{label}: {value!r}")

    @staticmethod
    def _require_contained(path: str, parent: str, label: str) -> str:
        """Return the canonical path only when it remains below parent."""
        canonical_path = os.path.realpath(os.path.abspath(path))
        canonical_parent = os.path.realpath(os.path.abspath(parent))
        try:
            contained = os.path.commonpath((canonical_path, canonical_parent)) == canonical_parent
        except ValueError:
            contained = False
        if not contained or canonical_path == canonical_parent:
            raise ValueError(f"{label}超出允许目录")
        return canonical_path

    def _deletion_paths(self, project_id: str):
        """Resolve deletion directories without following escapes."""
        self._validate_path_id(project_id, "项目ID")
        project_candidate = os.path.join(self.projects_dir, project_id)
        if os.path.islink(project_candidate):
            raise ValueError(f"项目目录不能是符号链接: {project_id}")
        project_path = self._require_contained(
            project_candidate, self.projects_dir, "项目"
        )
        images_candidate = os.path.join(project_path, 'images')
        annotations_candidate = os.path.join(project_path, 'annotations')
        if os.path.islink(images_candidate):
            raise ValueError(f"图片目录不能是符号链接: {project_id}")
        if os.path.islink(annotations_candidate):
            raise ValueError(f"标注目录不能是符号链接: {project_id}")
        images_path = self._require_contained(
            images_candidate, project_path, "图片目录"
        )
        annotations_path = self._require_contained(
            annotations_candidate, project_path, "标注目录"
        )
        return project_path, images_path, annotations_path

    @classmethod
    def _project_lock(cls, project_path: str):
        """Return the process-wide lock shared by managers for one project."""
        return shared_project_lock(project_path)

    def project_lock(self, project_id: str):
        """Expose the validated shared lock for project-scoped external writes."""
        project_path, _, _ = self._deletion_paths(project_id)
        return shared_project_lock(project_path)

    def _recover_pending_deletions(self, *directories: str) -> None:
        """Roll crash-left pending files back without ever deleting the only copy."""
        for directory in directories:
            if not os.path.isdir(directory):
                continue
            for filename in os.listdir(directory):
                if '.delete-' not in filename or not filename.endswith('.pending'):
                    continue
                pending_candidate = os.path.join(directory, filename)
                if os.path.islink(pending_candidate):
                    continue
                pending = self._require_contained(
                    pending_candidate, directory, "删除待恢复文件"
                )
                original_name, token_part = filename.rsplit('.delete-', 1)
                token = token_part[:-len('.pending')]
                original = self._require_contained(
                    os.path.join(directory, original_name), directory, "待恢复原文件"
                )
                if os.path.lexists(original):
                    recovery = self._require_contained(
                        f'{original}.rollback-recovery-{token or uuid.uuid4().hex}',
                        directory,
                        "冲突恢复文件",
                    )
                    if os.path.lexists(recovery):
                        recovery = self._require_contained(
                            f'{original}.rollback-recovery-{uuid.uuid4().hex}',
                            directory,
                            "冲突恢复文件",
                        )
                    os.replace(pending, recovery)
                else:
                    os.replace(pending, original)

    def _atomic_write_json(self, path: str, data: Dict, parent: str) -> None:
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.atomic-', suffix='.tmp', dir=parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        except Exception:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            raise

    def _remove_skipped_id(self, project_path: str, image_id: str) -> None:
        skipped = os.path.join(project_path, 'skipped.json')
        if os.path.islink(skipped):
            raise ValueError("跳过列表不能是符号链接")
        if not os.path.exists(skipped):
            return
        with open(skipped, 'r', encoding='utf-8') as f:
            data = json.load(f)
        values = data.get('skipped_images', [])
        updated = [value for value in values if value != image_id]
        if updated != values:
            data['skipped_images'] = updated
            self._atomic_write_json(skipped, data, project_path)

    def _recover_delete_journals(
        self, project_path: str, images_path: str, annotations_path: str
    ) -> None:
        directories = {'images': images_path, 'annotations': annotations_path}
        for filename in os.listdir(project_path):
            if not filename.startswith('.delete-transaction-') or not filename.endswith('.json'):
                continue
            marker_candidate = os.path.join(project_path, filename)
            if os.path.islink(marker_candidate):
                raise ValueError("删除事务标记不能是符号链接")
            marker = self._require_contained(marker_candidate, project_path, "删除事务标记")
            with open(marker, 'r', encoding='utf-8') as f:
                journal = json.load(f)
            token = journal.get('token')
            if not isinstance(token, str) or not token or '/' in token or '\\' in token:
                raise ValueError("无效删除事务标记")
            records = []
            for item in journal.get('records', []):
                directory = directories.get(item.get('directory'))
                if directory is None:
                    raise ValueError("无效删除事务目录")
                names = [item.get(key) for key in ('original', 'pending', 'tombstone')]
                if any(not isinstance(name, str) or os.path.basename(name) != name for name in names):
                    raise ValueError("无效删除事务文件名")
                records.append(tuple(
                    self._require_contained(os.path.join(directory, name), directory, "删除事务文件")
                    for name in names
                ))
            committed = journal.get('phase') == 'committed' or any(
                os.path.lexists(tombstone) for _, _, tombstone in records
            )
            if committed:
                for _, pending, tombstone in records:
                    if os.path.lexists(pending) and not os.path.lexists(tombstone):
                        os.replace(pending, tombstone)
                if journal.get('remove_skipped'):
                    self._remove_skipped_id(project_path, journal.get('image_id'))
            else:
                for original, pending, _ in records:
                    if not os.path.lexists(pending):
                        continue
                    if not os.path.lexists(original):
                        os.replace(pending, original)
                    else:
                        recovery = self._require_contained(
                            f'{original}.rollback-recovery-{token}',
                            os.path.dirname(original),
                            "事务冲突恢复文件",
                        )
                        os.replace(pending, recovery)
            os.unlink(marker)

    def _scavenge_tombstones(self, *directories: str) -> None:
        """Best-effort cleanup of committed deletion tombstones."""
        for directory in directories:
            try:
                if not os.path.isdir(directory):
                    continue
                filenames = os.listdir(directory)
            except Exception:
                continue
            for filename in filenames:
                if '.delete-' not in filename or not filename.endswith('.tombstone'):
                    continue
                try:
                    tombstone_candidate = os.path.join(directory, filename)
                    if os.path.islink(tombstone_candidate):
                        continue
                    tombstone = self._require_contained(
                        tombstone_candidate, directory, "删除暂存文件"
                    )
                    os.unlink(tombstone)
                except Exception:
                    pass

    def delete_image(self, project_id: str, image_id: str) -> bool:
        """Transactionally delete one exact image stem and its related state."""
        self._validate_path_id(image_id, "图片ID")
        paths = self._deletion_paths(project_id)
        with self._project_lock(paths[0]):
            return self._delete_image_locked(image_id, *paths)

    def _delete_image_locked(
        self, image_id: str, project_path: str, images_path: str,
        annotations_path: str
    ) -> bool:
        self._recover_delete_journals(project_path, images_path, annotations_path)
        self._recover_pending_deletions(images_path, annotations_path)

        matches = []
        if os.path.isdir(images_path):
            for filename in os.listdir(images_path):
                stem, suffix = os.path.splitext(filename)
                if stem == image_id and suffix.lower() in self.IMAGE_SUFFIXES:
                    candidate = os.path.join(images_path, filename)
                    if os.path.islink(candidate):
                        raise ValueError(f"图片不能是符号链接: {image_id}")
                    matches.append(
                        self._require_contained(
                            candidate, images_path, "图片"
                        )
                    )
        if not matches:
            raise FileNotFoundError(f"图片不存在: {image_id}")
        if len(matches) > 1:
            raise ValueError(f"图片ID对应多个文件: {image_id}")

        image_path = matches[0]
        annotation_candidate = os.path.join(annotations_path, f'{image_id}.json')
        if os.path.islink(annotation_candidate):
            raise ValueError(f"标注不能是符号链接: {image_id}")
        annotation_path = self._require_contained(
            annotation_candidate,
            annotations_path,
            "标注",
        )
        has_annotation = os.path.lexists(annotation_path)

        skipped_candidate = os.path.join(project_path, 'skipped.json')
        if os.path.islink(skipped_candidate):
            raise ValueError("跳过列表不能是符号链接")
        skipped_path = self._require_contained(
            skipped_candidate, project_path, "跳过列表"
        )
        skipped_data = None
        skipped_needs_update = False
        if os.path.lexists(skipped_path):
            # Canonicalization above rejects a skipped.json symlink outside the project.
            with open(skipped_path, 'r', encoding='utf-8') as f:
                skipped_data = json.load(f)
            skipped_images = skipped_data.get('skipped_images', [])
            if image_id in skipped_images:
                skipped_data['skipped_images'] = [
                    item for item in skipped_images if item != image_id
                ]
                skipped_needs_update = True

        # Error requests above are side-effect free; cleanup starts only after the
        # target and all related paths have been validated.
        self._scavenge_tombstones(images_path, annotations_path)

        token = uuid.uuid4().hex
        staged = []
        skipped_temp = None
        marker = None
        journal = None
        committed = False
        try:
            for source in ([image_path, annotation_path] if has_annotation else [image_path]):
                pending = self._require_contained(
                    f'{source}.delete-{token}.pending',
                    os.path.dirname(source),
                    "删除待提交文件",
                )
                tombstone = self._require_contained(
                    f'{source}.delete-{token}.tombstone',
                    os.path.dirname(source),
                    "删除已提交文件",
                )
                os.replace(source, pending)
                staged.append({
                    'source': source,
                    'pending': pending,
                    'tombstone': tombstone,
                    'current': pending,
                })

            journal = {
                'token': token,
                'image_id': image_id,
                'remove_skipped': skipped_needs_update,
                'phase': 'precommit',
                'records': [
                    {
                        'directory': (
                            'images' if os.path.dirname(record['source']) == images_path
                            else 'annotations'
                        ),
                        'original': os.path.basename(record['source']),
                        'pending': os.path.basename(record['pending']),
                        'tombstone': os.path.basename(record['tombstone']),
                    }
                    for record in staged
                ],
            }
            marker = self._require_contained(
                os.path.join(project_path, f'.delete-transaction-{token}.json'),
                project_path,
                "删除事务标记",
            )
            self._atomic_write_json(marker, journal, project_path)

            # A crash from this point leaves committed deletions and, at worst,
            # harmless stale skipped metadata. Pending names are rollback-only.
            for record in staged:
                os.replace(record['pending'], record['tombstone'])
                record['current'] = record['tombstone']
            journal['phase'] = 'committed'
            self._atomic_write_json(marker, journal, project_path)

            if skipped_needs_update:
                fd, skipped_temp = tempfile.mkstemp(
                    prefix='.skipped-', suffix='.tmp', dir=project_path
                )
                skipped_temp = self._require_contained(
                    skipped_temp, project_path, "跳过列表临时文件"
                )
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(skipped_data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(skipped_temp, skipped_path)
                skipped_temp = None
            os.unlink(marker)
            marker = None
            committed = True
        except Exception as staging_error:
            rollback_failures = []
            if not committed:
                for record in reversed(staged):
                    source = record['source']
                    staged_path = record['current']
                    try:
                        os.replace(staged_path, source)
                    except Exception as rollback_error:
                        recovery_path = self._require_contained(
                            f'{source}.rollback-recovery-{token}',
                            os.path.dirname(source),
                            "回滚恢复文件",
                        )
                        try:
                            os.replace(staged_path, recovery_path)
                            rollback_failures.append(
                                "staged={staged} recovery={source} error={error} "
                                "preserved={preserved} state=source-missing".format(
                                    staged=staged_path,
                                    source=source,
                                    error=rollback_error,
                                    preserved=recovery_path,
                                )
                            )
                        except Exception as preservation_error:
                            rollback_failures.append(
                                "staged={staged} recovery={source} error={error} "
                                "preservation-error={preservation_error} state=staged-copy-at-risk".format(
                                    staged=staged_path,
                                    source=source,
                                    error=rollback_error,
                                    preservation_error=preservation_error,
                                )
                            )
                if skipped_temp is not None:
                    try:
                        os.unlink(skipped_temp)
                    except Exception as rollback_error:
                        rollback_failures.append(
                            "temporary={temporary} recovery=unlink error={error}".format(
                                temporary=skipped_temp,
                                error=rollback_error,
                            )
                        )
            if rollback_failures:
                raise RuntimeError(
                    "delete rollback failed after {original}; unresolved recovery state: {details}".format(
                        original=staging_error,
                        details="; ".join(rollback_failures),
                    )
                ) from staging_error
            if marker is not None and os.path.lexists(marker):
                try:
                    os.unlink(marker)
                    marker = None
                except OSError as marker_error:
                    raise RuntimeError(
                        f"delete rollback restored files but journal remains: {marker}"
                    ) from marker_error
            raise

        for record in staged:
            try:
                os.unlink(record['tombstone'])
            except OSError:
                pass
        return True
    
    def create_project(self, project_name: str, description: str, 
                      categories: List[str]) -> Dict:
        """创建新项目"""
        project_id = project_name.lower().replace(" ", "_")
        project_path = os.path.join(self.projects_dir, project_id)
        
        if os.path.exists(project_path):
            raise ValueError(f"项目 {project_name} 已存在")
        
        # 创建项目目录结构
        os.makedirs(project_path, exist_ok=True)
        os.makedirs(os.path.join(project_path, "images"), exist_ok=True)
        os.makedirs(os.path.join(project_path, "annotations"), exist_ok=True)
        os.makedirs(os.path.join(project_path, "exports"), exist_ok=True)
        
        # 创建项目配置
        project_config = {
            "id": project_id,
            "name": project_name,
            "description": description,
            "categories": categories,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "image_count": 0,
            "annotated_count": 0,
            "version": 1
        }
        
        config_path = os.path.join(project_path, "project.json")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(project_config, f, indent=2, ensure_ascii=False)
        
        return project_config
    
    def list_projects(self) -> List[Dict]:
        """列出所有项目"""
        projects = []
        
        if not os.path.exists(self.projects_dir):
            return projects
        
        for project_id in os.listdir(self.projects_dir):
            project_path = os.path.join(self.projects_dir, project_id)
            config_path = os.path.join(project_path, "project.json")
            
            if os.path.isdir(project_path) and os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    
                    # 更新统计信息
                    config = self._update_project_stats(project_id, config)
                    projects.append(config)
                except Exception as e:
                    print(f"读取项目配置失败: {project_id}, 错误: {e}")
        
        return sorted(projects, key=lambda x: x['updated_at'], reverse=True)
    
    def get_project(self, project_id: str) -> Optional[Dict]:
        """获取项目详情"""
        project_path = os.path.join(self.projects_dir, project_id)
        config_path = os.path.join(project_path, "project.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 更新统计信息
        config = self._update_project_stats(project_id, config)
        
        return config
    
    def update_project(self, project_id: str, updates: Dict) -> Dict:
        """更新项目配置"""
        project_path = os.path.join(self.projects_dir, project_id)
        config_path = os.path.join(project_path, "project.json")
        
        if not os.path.exists(config_path):
            raise ValueError(f"项目不存在: {project_id}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 更新字段
        allowed_fields = ['name', 'description', 'categories']
        for field in allowed_fields:
            if field in updates:
                config[field] = updates[field]
        
        config['updated_at'] = datetime.now().isoformat()
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        return config
    
    def delete_project(self, project_id: str) -> bool:
        """删除项目"""
        project_path = os.path.join(self.projects_dir, project_id)
        
        if not os.path.exists(project_path):
            raise ValueError(f"项目不存在: {project_id}")
        
        try:
            shutil.rmtree(project_path)
            return True
        except Exception as e:
            print(f"删除项目失败: {e}")
            return False
    
    def _update_project_stats(self, project_id: str, config: Dict) -> Dict:
        """更新项目统计信息"""
        project_path = os.path.join(self.projects_dir, project_id)
        images_path = os.path.join(project_path, "images")
        annotations_path = os.path.join(project_path, "annotations")
        
        # 统计图片数量
        image_count = 0
        if os.path.exists(images_path):
            image_count = len([f for f in os.listdir(images_path) 
                             if f.lower().endswith(self.IMAGE_SUFFIXES)])
        
        # 统计已标注图片数量和总标注框数量
        annotated_count = 0
        total_boxes = 0
        if os.path.exists(annotations_path):
            for filename in os.listdir(annotations_path):
                if filename.endswith('.json'):
                    annotated_count += 1
                    # 读取标注文件，统计标注框数量
                    annotation_file = os.path.join(annotations_path, filename)
                    try:
                        with open(annotation_file, 'r', encoding='utf-8') as f:
                            annotation_data = json.load(f)
                            annotations = annotation_data.get('annotations', [])
                            total_boxes += len(annotations)
                    except Exception as e:
                        print(f"读取标注文件失败 {filename}: {e}")
        
        config['image_count'] = image_count
        config['annotated_count'] = annotated_count
        config['total_boxes'] = total_boxes  # 新增：总标注框数量
        
        # 保存更新后的配置
        config_path = os.path.join(project_path, "project.json")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        return config
    
    def get_project_images(self, project_id: str, page: int = 1, 
                          page_size: int = 20) -> Dict:
        """获取项目图片列表（分页）"""
        paths = self._deletion_paths(project_id)
        with self._project_lock(paths[0]):
            return self._get_project_images_locked(
                project_id, page, page_size, *paths
            )

    def _get_project_images_locked(
        self, project_id: str, page: int, page_size: int,
        project_path: str, images_path: str, annotations_path: str
    ) -> Dict:
        self._recover_delete_journals(project_path, images_path, annotations_path)
        self._recover_pending_deletions(images_path, annotations_path)
        self._scavenge_tombstones(images_path, annotations_path)
        skipped_file = os.path.join(project_path, "skipped.json")
        
        if not os.path.exists(images_path):
            return {
                "images": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "total_pages": 0
            }
        
        # 读取跳过的图片列表
        skipped_images = set()
        if os.path.exists(skipped_file):
            try:
                with open(skipped_file, 'r', encoding='utf-8') as f:
                    skipped_data = json.load(f)
                    skipped_images = set(skipped_data.get('skipped_images', []))
            except Exception as e:
                print(f"读取跳过列表失败: {e}")
        
        # 获取所有图片
        all_images = []
        for filename in os.listdir(images_path):
            if filename.lower().endswith(self.IMAGE_SUFFIXES):
                image_id = os.path.splitext(filename)[0]
                annotation_file = os.path.join(annotations_path, f"{image_id}.json")
                
                all_images.append({
                    "id": image_id,
                    "filename": filename,
                    "path": (
                        f"/api/projects/{quote(project_id, safe='')}/images/"
                        f"{quote(filename, safe='')}"
                    ),
                    "annotated": os.path.exists(annotation_file),
                    "skipped": image_id in skipped_images
                })
        
        # 排序：按文件名自然排序，保持固定顺序
        # 这样刷新页面后图片顺序不会改变
        import re
        def natural_sort_key(item):
            """自然排序函数，使 1_2.jpg < 1_10.jpg"""
            filename = item['filename']
            # 提取数字和文本部分
            parts = re.split(r'(\d+)', filename)
            # 将数字部分转换为整数，文本部分保持不变
            return [int(p) if p.isdigit() else p.lower() for p in parts]
        
        all_images.sort(key=natural_sort_key)
        
        # 分页
        total = len(all_images)
        total_pages = (total + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size
        
        return {
            "images": all_images[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }
    
    def set_image_skipped(self, project_id: str, image_id: str, skipped: bool = True) -> bool:
        """设置图片的跳过状态"""
        project_path, _, _ = self._deletion_paths(project_id)
        with self._project_lock(project_path):
            images_path = os.path.join(project_path, 'images')
            matches = [
                filename for filename in os.listdir(images_path)
                if os.path.splitext(filename)[0] == image_id
                and os.path.splitext(filename)[1].lower() in self.IMAGE_SUFFIXES
                and not os.path.islink(os.path.join(images_path, filename))
            ] if os.path.isdir(images_path) else []
            if len(matches) != 1:
                return False
            skipped_file = os.path.join(project_path, "skipped.json")
            skipped_images = set()
            if os.path.exists(skipped_file):
                try:
                    with open(skipped_file, 'r', encoding='utf-8') as f:
                        skipped_data = json.load(f)
                        skipped_images = set(skipped_data.get('skipped_images', []))
                except Exception as e:
                    print(f"读取跳过列表失败: {e}")

            if skipped:
                skipped_images.add(image_id)
            else:
                skipped_images.discard(image_id)

            temporary = None
            try:
                fd, temporary = tempfile.mkstemp(
                    prefix='.skipped-', suffix='.tmp', dir=project_path
                )
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump({
                        'skipped_images': list(skipped_images),
                        'updated_at': datetime.now().isoformat()
                    }, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary, skipped_file)
                return True
            except Exception as e:
                if temporary is not None:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
                print(f"保存跳过列表失败: {e}")
                return False
