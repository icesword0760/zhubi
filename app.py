"""
朱笔 Zhubi 主应用
Flask后端API服务器
"""

import os
import sys
from datetime import datetime

# 🔧 强制离线模式 - 禁止从 Hugging Face 下载
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_DATASETS_OFFLINE'] = '1'

import yaml
from flask import Flask, request, jsonify, send_file, send_from_directory, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
from PIL import Image
import traceback

# 导入后端模块
from backend.project_manager import ProjectManager
from backend.annotation_manager import AnnotationManager
from backend.export_manager import ExportManager
from backend.train_manager import TrainManager
from backend.yolo_train_manager import YoloTrainManager
from backend.model_validator import ModelValidator

# 加载配置
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_BASE_DIR, 'config.yaml'), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 上游 OmniParser 仓库位置：提供 weights/（基础权重）和 util/（OmniParser 对比、负样本检测）。
# 优先级：环境变量 OMNIPARSER_ROOT > config.paths.omniparser_root > 同级目录 ../OmniParser
OMNIPARSER_ROOT = os.path.abspath(
    os.environ.get('OMNIPARSER_ROOT')
    or config.get('paths', {}).get('omniparser_root')
    or os.path.join(_BASE_DIR, '..', 'OmniParser')
)
os.environ.setdefault('OMNIPARSER_ROOT', OMNIPARSER_ROOT)
if OMNIPARSER_ROOT not in sys.path:
    sys.path.append(OMNIPARSER_ROOT)


def resolve_model_path(path):
    """把界面/配置里的模型路径转成绝对路径。

    - 绝对路径原样返回
    - weights/... 或 ../weights/... 指向 OmniParser 的基础权重目录
    - 其余相对路径（如 data/models/...）相对于本应用目录
    """
    if not path:
        return path
    if os.path.isabs(path):
        return path
    normalized = path.replace('\\', '/')
    if normalized.startswith('../weights/') or normalized.startswith('weights/'):
        return os.path.join(OMNIPARSER_ROOT, 'weights', normalized.split('weights/', 1)[1])
    return os.path.join(_BASE_DIR, normalized)


# 配置中的基础权重路径统一解析为绝对路径，后端各管理器直接使用
for _key in ('base_model_path', 'processor_path', 'yolo_model_path'):
    if config.get('training', {}).get(_key):
        config['training'][_key] = resolve_model_path(config['training'][_key])

# 创建Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = config['server']['secret_key']
app.config['MAX_CONTENT_LENGTH'] = config['data']['max_upload_size'] * 1024 * 1024
CORS(app)

# 创建数据目录
os.makedirs(config['data']['projects_dir'], exist_ok=True)
os.makedirs(config['data']['models_dir'], exist_ok=True)
os.makedirs(config['data']['exports_dir'], exist_ok=True)
os.makedirs(config['data']['logs_dir'], exist_ok=True)

# 初始化管理器
# 将相对路径转换为绝对路径
import os as _os
_app_dir = _os.path.dirname(_os.path.abspath(__file__))

def _resolve_path(path):
    """将相对路径转换为绝对路径"""
    if _os.path.isabs(path):
        return path
    return _os.path.join(_app_dir, path)

projects_dir = _resolve_path(config['data']['projects_dir'])
exports_dir = _resolve_path(config['data']['exports_dir'])
models_dir = _resolve_path(config['data']['models_dir'])

project_manager = ProjectManager(projects_dir)
annotation_manager = AnnotationManager(projects_dir)
export_manager = ExportManager(projects_dir, exports_dir)
train_manager = TrainManager(models_dir, config)
yolo_train_manager = YoloTrainManager(models_dir, config)
model_validator = ModelValidator(models_dir, config)


# ==================== 项目管理API ====================

@app.route('/api/projects', methods=['GET'])
def list_projects():
    """列出所有项目"""
    try:
        projects = project_manager.list_projects()
        return jsonify({"success": True, "projects": projects})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects', methods=['POST'])
def create_project():
    """创建新项目"""
    try:
        data = request.json
        project = project_manager.create_project(
            project_name=data['name'],
            description=data.get('description', ''),
            categories=data['categories']
        )
        return jsonify({"success": True, "project": project})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/projects/<project_id>', methods=['GET'])
def get_project(project_id):
    """获取项目详情"""
    try:
        project = project_manager.get_project(project_id)
        if project:
            return jsonify({"success": True, "project": project})
        return jsonify({"success": False, "error": "项目不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>', methods=['PUT'])
def update_project(project_id):
    """更新项目"""
    try:
        data = request.json
        project = project_manager.update_project(project_id, data)
        return jsonify({"success": True, "project": project})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/projects/<project_id>/crop-icons', methods=['POST'])
def crop_icons(project_id):
    """裁切图标并准备双格式数据"""
    try:
        data = request.json
        
        from backend.crop_manager import CropManager
        crop_manager = CropManager(config['data']['projects_dir'])
        
        result = crop_manager.crop_and_save(
            project_id=project_id,
            image_id=data['image_id'],
            image_filename=data['image_filename'],
            image_width=data['image_width'],
            image_height=data['image_height'],
            bboxes=data['bboxes']
        )
        
        return jsonify({"success": True, **result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>/batch-crop', methods=['POST'])
def batch_crop(project_id):
    """批量裁切所有已标注图片"""
    try:
        from backend.crop_manager import CropManager
        crop_manager = CropManager(config['data']['projects_dir'])
        
        result = crop_manager.batch_crop_project(project_id)
        
        return jsonify({"success": True, **result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    """删除项目"""
    try:
        success = project_manager.delete_project(project_id)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "删除失败"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>/images', methods=['GET'])
def get_project_images(project_id):
    """获取项目图片列表"""
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        
        result = project_manager.get_project_images(project_id, page, page_size)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>/images/<image_id>', methods=['DELETE'])
def delete_image(project_id, image_id):
    """删除单张项目图片及其标注和跳过状态。"""
    try:
        project_manager.delete_image(project_id, image_id)
        return jsonify({"success": True})
    except FileNotFoundError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception:
        traceback.print_exc()
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


@app.route('/api/projects/<project_id>/images/<filename>', methods=['GET'])
def get_image(project_id, filename):
    """获取图片"""
    try:
        image_path = os.path.join(config['data']['projects_dir'], project_id, 'images', filename)
        if os.path.exists(image_path):
            return send_file(image_path)
        return jsonify({"success": False, "error": "图片不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>/images/<image_id>/skip', methods=['POST'])
def skip_image(project_id, image_id):
    """设置图片跳过状态"""
    try:
        data = request.json
        skipped = data.get('skipped', True)
        
        success = project_manager.set_image_skipped(project_id, image_id, skipped)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>/upload', methods=['POST'])
def upload_images(project_id):
    """上传图片"""
    try:
        if 'images' not in request.files:
            return jsonify({"success": False, "error": "没有上传文件"}), 400
        
        files = request.files.getlist('images')
        uploaded = []
        errors = []
        
        with project_manager.project_lock(project_id):
            images_dir = os.path.join(projects_dir, project_id, 'images')
            os.makedirs(images_dir, exist_ok=True)

            for file in files:
                if file and file.filename:
                    try:
                        # 验证文件类型
                        ext = file.filename.rsplit('.', 1)[1].lower()
                        if ext not in config['data']['allowed_extensions']:
                            errors.append(f"{file.filename}: 不支持的文件格式")
                            continue

                        filename = secure_filename(file.filename)
                        filepath = os.path.join(images_dir, filename)

                        # 保存并验证图片 while the project transaction lock is held.
                        file.save(filepath)
                        img = Image.open(filepath)
                        img.verify()

                        uploaded.append(filename)
                    except Exception as e:
                        errors.append(f"{file.filename}: {str(e)}")
        
        return jsonify({
            "success": True,
            "uploaded": len(uploaded),
            "files": uploaded,
            "errors": errors
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== 标注管理API ====================

@app.route('/api/projects/<project_id>/annotations/<image_id>', methods=['GET'])
def get_annotation(project_id, image_id):
    """获取标注"""
    try:
        annotation = annotation_manager.get_annotation(project_id, image_id)
        if annotation:
            return jsonify({"success": True, "annotation": annotation})
        return jsonify({"success": True, "annotation": None})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>/annotations/<image_id>', methods=['POST'])
def save_annotation(project_id, image_id):
    """保存标注"""
    try:
        data = request.json
        annotations = data.get('annotations', [])
        
        result = annotation_manager.save_annotation(project_id, image_id, annotations)
        return jsonify({"success": True, "annotation": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>/annotations/<image_id>', methods=['DELETE'])
def delete_annotation(project_id, image_id):
    """删除标注"""
    try:
        success = annotation_manager.delete_annotation(project_id, image_id)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>/stats', methods=['GET'])
def get_annotation_stats(project_id):
    """获取标注统计"""
    try:
        stats = annotation_manager.get_annotation_stats(project_id)
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/projects/<project_id>/validate', methods=['GET'])
def validate_annotations(project_id):
    """验证标注质量"""
    try:
        validation = annotation_manager.validate_annotations(project_id)
        return jsonify({"success": True, "validation": validation})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== 导出管理API ====================

@app.route('/api/projects/<project_id>/export', methods=['POST'])
def export_project(project_id):
    """导出项目"""
    try:
        data = request.json
        export_format = data.get('format', 'coco')
        split_ratios = tuple(data.get('split', [0.7, 0.2, 0.1]))
        augmentation = data.get('augmentation', False)
        
        zip_path = export_manager.export_project(
            project_id, export_format, split_ratios, augmentation
        )
        
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=os.path.basename(zip_path)
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== 训练管理API ====================

@app.route('/api/projects/<project_id>/train', methods=['POST'])
def start_training(project_id):
    """开始训练（流式输出日志）"""
    try:
        print(f"=== 收到训练请求 ===")
        print(f"项目ID: {project_id}")
        data = request.json
        print(f"请求数据: {data}")
        
        model_type = data.get('model_type', 'florence2')  # 'florence2' 或 'yolo'
        print(f"模型类型: {model_type}")
        
        def generate():
            try:
                if model_type == 'yolo':
                    # YOLO训练，返回带进度的JSON格式
                    print("开始YOLO训练流...")
                    for progress_data in yolo_train_manager.start_training(project_id, data):
                        try:
                            import json
                            line = f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"
                            print(f"发送YOLO数据: {progress_data}")
                            yield line
                        except (BrokenPipeError, ConnectionError) as e:
                            # 客户端断开连接，但训练继续
                            print(f"⚠️ 客户端连接断开: {e}，训练继续在后台运行")
                            break
                else:
                    # Florence-2训练，返回带进度的JSON格式
                    print("开始Florence-2训练流...")
                    for progress_data in train_manager.start_training(project_id, data):
                        try:
                            import json
                            line = f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"
                            print(f"发送Florence-2数据: {progress_data}")
                            yield line
                        except (BrokenPipeError, ConnectionError) as e:
                            # 客户端断开连接，但训练继续
                            print(f"⚠️ 客户端连接断开: {e}，训练继续在后台运行")
                            break
                print("训练流结束")
            except BrokenPipeError:
                # 忽略管道断裂错误
                print("⚠️ SSE连接已断开，训练已在后台继续")
            except Exception as e:
                import json
                import traceback
                error_msg = {
                    'type': 'error',
                    'message': f'训练过程出错: {str(e)}\n{traceback.format_exc()}',
                    'progress': 0
                }
                print(f"训练出错: {error_msg}")
                try:
                    yield f"data: {json.dumps(error_msg, ensure_ascii=False)}\n\n"
                except (BrokenPipeError, ConnectionError):
                    print("⚠️ 无法发送错误消息，连接已断开")
        
        return Response(generate(), mimetype='text/event-stream')
    except Exception as e:
        import traceback
        print(f"启动训练失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/projects/<project_id>/train/progress', methods=['GET'])
def get_training_progress(project_id):
    """获取实时训练进度（用于轮询）"""
    try:
        import os
        import json
        
        # 查找进度文件 - 使用绝对路径
        models_dir = config['data']['models_dir']
        if not os.path.isabs(models_dir):
            # 相对于应用目录的相对路径
            models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), models_dir)
        
        progress_file = os.path.join(models_dir, f"{project_id}_training_progress.json")
        
        print(f"[进度API] 查找进度文件: {progress_file}")  # 调试日志
        
        if not os.path.exists(progress_file):
            print(f"[进度API] 文件不存在")  # 调试日志
            return jsonify({
                'success': False,
                'status': 'not_found',
                'message': '没有正在进行的训练'
            })
        
        # 读取进度
        with open(progress_file, 'r', encoding='utf-8') as f:
            progress_data = json.load(f)
        
        print(f"[进度API] 读取成功: {progress_data}")  # 调试日志
        
        return jsonify({
            'success': True,
            'status': progress_data.get('status', 'training'),
            'data': progress_data
        })
        
    except Exception as e:
        import traceback
        print(f"获取训练进度失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/projects/<project_id>/train/stop', methods=['POST'])
def stop_training(project_id):
    """停止训练"""
    try:
        import os
        import signal
        import json
        
        print(f"[停止训练] 项目: {project_id}")
        
        # 查找进度文件，获取训练进程信息
        models_dir = config['data']['models_dir']
        if not os.path.isabs(models_dir):
            models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), models_dir)
        
        progress_file = os.path.join(models_dir, f"{project_id}_training_progress.json")
        log_file = os.path.join(models_dir, f"{project_id}_training_log.txt")
        
        # 删除进度和日志文件，停止训练循环
        stopped_files = []
        if os.path.exists(progress_file):
            os.remove(progress_file)
            stopped_files.append('progress')
        if os.path.exists(log_file):
            # 在日志文件末尾添加停止标记
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write('\n⛔ 训练已被手动停止\n')
            stopped_files.append('log')
        
        # 尝试终止训练进程（通过杀死包含项目ID的Python进程）
        killed_pids = []
        try:
            import subprocess
            # 查找相关的训练进程
            result = subprocess.run(
                ['ps', 'aux'], 
                capture_output=True, 
                text=True
            )
            lines = result.stdout.split('\n')
            for line in lines:
                if 'train_manager' in line and project_id in line and 'python' in line.lower():
                    parts = line.split()
                    if len(parts) > 1:
                        pid = int(parts[1])
                        try:
                            os.kill(pid, signal.SIGTERM)
                            killed_pids.append(pid)
                            print(f"[停止训练] 终止进程: {pid}")
                        except:
                            pass
        except Exception as e:
            print(f"[停止训练] 终止进程失败: {e}")
        
        # 🔧 关键：清理内存资源
        print("[停止训练] 开始清理内存...")
        try:
            import gc
            import torch
            
            # 强制垃圾回收
            collected = gc.collect()
            print(f"[停止训练] 垃圾回收: {collected} 个对象")
            
            # 清理PyTorch缓存
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                print("[停止训练] CUDA缓存已清理")
            
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                torch.mps.empty_cache()
                print("[停止训练] MPS缓存已清理")
            
            print("[停止训练] 内存清理完成")
        except Exception as e:
            print(f"[停止训练] 内存清理失败: {e}")
        
        return jsonify({
            'success': True,
            'message': '训练已停止，内存已清理',
            'stopped_files': stopped_files,
            'killed_pids': killed_pids
        })
    except Exception as e:
        import traceback
        print(f"[停止训练] 失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/projects/<project_id>/train/finish', methods=['POST'])
def finish_training(project_id):
    """完成训练（保存当前模型并正常结束）"""
    try:
        import os
        
        print(f"[完成训练] 项目: {project_id}")
        
        # 获取models目录
        models_dir = config['data']['models_dir']
        if not os.path.isabs(models_dir):
            models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), models_dir)
        
        # 创建完成标志文件
        finish_flag_file = os.path.join(models_dir, f"{project_id}_finish_flag.txt")
        
        with open(finish_flag_file, 'w', encoding='utf-8') as f:
            f.write(f'用户请求完成训练\n创建时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        
        print(f"[完成训练] 已创建完成标志文件: {finish_flag_file}")
        
        # 在日志文件中添加标记
        log_file = os.path.join(models_dir, f"{project_id}_training_log.txt")
        if os.path.exists(log_file):
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write('\n👤 用户请求完成训练，正在保存当前模型...\n')
        
        return jsonify({
            'success': True,
            'message': '✅ 完成请求已发送，训练将立即停止并保存当前模型',
            'flag_file': finish_flag_file
        })
    except Exception as e:
        import traceback
        print(f"[完成训练] 失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/projects/<project_id>/train/resume', methods=['POST'])
def resume_training(project_id):
    """继续训练（从已保存的模型继续）"""
    try:
        data = request.json
        
        print(f"[继续训练] 项目: {project_id}")
        print(f"[继续训练] 请求数据: {data}")
        
        # 获取模型路径
        model_timestamp = data.get('model_timestamp')
        if not model_timestamp:
            return jsonify({
                'success': False,
                'error': '缺少model_timestamp参数'
            })
        
        models_dir = config['data']['models_dir']
        if not os.path.isabs(models_dir):
            models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), models_dir)
        
        model_path = os.path.join(models_dir, project_id, model_timestamp, 'final_model')
        
        # 检查模型是否存在
        if not os.path.exists(model_path):
            return jsonify({
                'success': False,
                'error': f'模型不存在: {model_path}'
            })
        
        print(f"[继续训练] 模型路径: {model_path}")
        
        # 构建训练配置
        train_config = {
            'project_id': project_id,
            'resume_from': model_path,  # 🔑 关键参数
            'epochs': data.get('additional_epochs', 10),
            'batch_size': data.get('batch_size', config['training']['default_batch_size']),
            'learning_rate': data.get('learning_rate', 5e-7),  # 默认更小的LR
            'warmup_steps': data.get('warmup_steps', 0),
            'weight_decay': data.get('weight_decay', config['training']['default_weight_decay']),
            'max_grad_norm': data.get('max_grad_norm', config['training']['default_max_grad_norm']),
            'gradient_accumulation_steps': data.get('gradient_accumulation_steps', 1),
            'target_loss': data.get('target_loss'),
            'early_stop_patience': data.get('early_stop_patience', 3),
            'reduce_lr_config': data.get('reduce_lr_config', {}),
            'device': data.get('device', 'auto'),
            'use_lora': False  # 模型已有LoRA，不需要重新应用
        }
        
        print(f"[继续训练] 训练配置: {train_config}")
        
        # 开始继续训练
        def generate():
            try:
                for update in train_manager.start_training(project_id, train_config):
                    yield json.dumps(update, ensure_ascii=False) + '\n'
            except Exception as e:
                import traceback
                print(f"[继续训练] 训练失败: {str(e)}")
                print(traceback.format_exc())
                yield json.dumps({
                    'type': 'error',
                    'message': f'训练失败: {str(e)}'
                }, ensure_ascii=False) + '\n'
        
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
        
    except Exception as e:
        import traceback
        print(f"[继续训练] 失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/system/cleanup', methods=['POST'])
def cleanup_memory():
    """清理系统内存"""
    try:
        import gc
        import torch
        
        print("[内存清理] 开始清理...")
        
        # 强制垃圾回收
        collected = gc.collect()
        
        # 清理PyTorch缓存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print("[内存清理] CUDA缓存已清理")
        
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            torch.mps.empty_cache()
            print("[内存清理] MPS缓存已清理")
        
        print(f"[内存清理] 完成，回收了 {collected} 个对象")
        
        return jsonify({
            'success': True,
            'message': f'内存清理完成，回收了 {collected} 个对象'
        })
        
    except Exception as e:
        import traceback
        print(f"[停止训练] 失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/projects/<project_id>/train/logs', methods=['GET'])
def get_training_logs(project_id):
    """获取实时训练日志（用于轮询）"""
    try:
        import os
        
        # 查找日志文件 - 使用绝对路径
        models_dir = config['data']['models_dir']
        if not os.path.isabs(models_dir):
            # 相对于应用目录的相对路径
            models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), models_dir)
        
        log_file = os.path.join(models_dir, f"{project_id}_training_log.txt")
        
        print(f"[日志API] 查找日志文件: {log_file}")
        
        if not os.path.exists(log_file):
            print(f"[日志API] 文件不存在")
            return jsonify({
                'success': True,
                'logs': '',
                'message': '日志文件不存在'
            })
        
        # 读取日志
        with open(log_file, 'r', encoding='utf-8') as f:
            log_content = f.read()
        
        print(f"[日志API] 读取成功，内容长度: {len(log_content)}")
        
        return jsonify({
            'success': True,
            'logs': log_content
        })
        
    except Exception as e:
        import traceback
        print(f"获取训练日志失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/models', methods=['GET'])
def list_models():
    """列出所有训练好的模型"""
    try:
        models = train_manager.list_trained_models()
        return jsonify({"success": True, "models": models})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/models/<project_id>', methods=['GET'])
def get_model_info(project_id):
    """获取模型信息"""
    try:
        info = train_manager.get_model_info(project_id)
        if info:
            return jsonify({"success": True, "model": info})
        return jsonify({"success": False, "error": "模型不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/models/<project_id>', methods=['DELETE'])
def delete_model(project_id):
    """删除模型"""
    try:
        success = train_manager.delete_model(project_id)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== 模型验证API ====================

@app.route('/api/models/validate', methods=['POST'])
def validate_model():
    """验证单个模型"""
    try:
        # 检查是否有上传的图片
        if 'image' not in request.files:
            return jsonify({"success": False, "error": "未上传图片"}), 400
        
        file = request.files['image']
        model_path = request.form.get('model_path')
        model_type = request.form.get('model_type', 'yolo')
        conf_threshold = float(request.form.get('conf_threshold', 0.25))
        
        if not model_path:
            return jsonify({"success": False, "error": "未指定模型路径"}), 400
        model_path = resolve_model_path(model_path)

        # 保存临时图片
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        
        try:
            # 验证模型
            if model_type == 'yolo':
                result = model_validator.validate_yolo(model_path, tmp_path, conf_threshold)
            else:
                result = model_validator.validate_florence2(model_path, tmp_path)
            
            return jsonify(result)
        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/models/compare', methods=['POST'])
def compare_models():
    """对比两个模型"""
    try:
        # 检查是否有上传的图片
        if 'image' not in request.files:
            return jsonify({"success": False, "error": "未上传图片"}), 400
        
        file = request.files['image']
        model_a_path = request.form.get('model_a_path')
        model_b_path = request.form.get('model_b_path')
        model_type = request.form.get('model_type', 'yolo')
        
        if not model_a_path or not model_b_path:
            return jsonify({"success": False, "error": "未指定模型路径"}), 400
        model_a_path = resolve_model_path(model_a_path)
        model_b_path = resolve_model_path(model_b_path)

        # 保存临时图片
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        
        try:
            # 对比模型
            result = model_validator.compare_models(
                model_a_path, model_b_path, tmp_path, model_type
            )
            return jsonify(result)
        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== OmniParser API ====================

@app.route('/api/omniparser/process', methods=['POST'])
def process_with_omniparser():
    """使用OmniParser处理图片（双模型版本）"""
    try:
        # 检查是否有上传的图片
        if 'image' not in request.files:
            return jsonify({"success": False, "error": "未上传图片"}), 400
        
        file = request.files['image']
        
        # 获取两个模型路径
        yolo_model_path = request.form.get('yolo_model_path', 'weights/icon_detect/model.pt')
        florence2_model_path = request.form.get('florence2_model_path', 'weights/icon_caption_florence')
        
        box_threshold = float(request.form.get('box_threshold', 0.05))
        iou_threshold = float(request.form.get('iou_threshold', 0.1))
        imgsz = int(request.form.get('imgsz', 640))
        use_paddleocr = request.form.get('use_paddleocr', 'true').lower() == 'true'
        temperature = float(request.form.get('temperature', 0.7))
        repetition_penalty = float(request.form.get('repetition_penalty', 1.5))
        
        print(f"🎯 使用模型组合:")
        print(f"  YOLO: {yolo_model_path}")
        print(f"  Florence-2: {florence2_model_path}")
        print(f"  Temperature: {temperature}")
        print(f"  Repetition Penalty: {repetition_penalty}")
        
        # 保存临时图片
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        
        try:
            # 导入 OmniParser 的工具模块（来自 OMNIPARSER_ROOT）
            try:
                from util.utils import get_som_labeled_img, get_caption_model_processor, get_yolo_model, check_ocr_box
            except ImportError as import_error:
                raise RuntimeError(
                    f"未找到 OmniParser 的 util 模块，请设置 OMNIPARSER_ROOT 指向 OmniParser 仓库（当前: {OMNIPARSER_ROOT}）"
                ) from import_error
            from PIL import Image
            import io
            import base64

            # 处理模型路径：weights/ 指向 OmniParser 基础权重，data/ 指向本应用目录
            yolo_model_path = resolve_model_path(yolo_model_path)
            florence2_model_path = resolve_model_path(florence2_model_path)

            print(f"📦 解析后的YOLO路径: {yolo_model_path}")
            print(f"📦 解析后的Florence-2路径: {florence2_model_path}")
            
            # 验证路径是否存在
            if not os.path.exists(yolo_model_path):
                raise FileNotFoundError(f"YOLO模型文件不存在: {yolo_model_path}")
            if not os.path.exists(florence2_model_path):
                raise FileNotFoundError(f"Florence-2模型目录不存在: {florence2_model_path}")
            
            # 读取图片
            image = Image.open(tmp_path)
            
            # 加载YOLO检测模型
            print(f"📦 加载YOLO模型...")
            som_model = get_yolo_model(model_path=yolo_model_path)
            
            # 加载Florence-2识别模型
            print(f"📦 加载Florence-2模型...")
            # 🔧 修复：显式指定device，确保使用MPS（Mac）或CUDA（GPU）
            import torch
            device = 'mps' if torch.backends.mps.is_available() else ('cuda' if torch.cuda.is_available() else 'cpu')
            print(f"🎯 使用设备: {device}")
            caption_model_processor = get_caption_model_processor(
                model_name="florence2", 
                model_name_or_path=florence2_model_path,
                device=device
            )
            
            # 准备绘图配置
            box_overlay_ratio = max(image.size) / 3200
            draw_bbox_config = {
                'text_scale': 0.8 * box_overlay_ratio,
                'text_thickness': max(int(2 * box_overlay_ratio), 1),
                'text_padding': max(int(3 * box_overlay_ratio), 1),
                'thickness': max(int(3 * box_overlay_ratio), 1),
            }
            
            # OCR处理（与omni.py保持一致）
            # 如果 use_paddleocr 为 False，完全跳过OCR
            if use_paddleocr:
                try:
                    ocr_bbox_rslt, is_goal_filtered = check_ocr_box(
                        image, 
                        display_img=False, 
                        output_bb_format='xyxy',
                        goal_filtering=None,
                        easyocr_args={'paragraph': False, 'text_threshold': 0.5},
                        use_paddleocr=use_paddleocr
                    )
                    text, ocr_bbox = ocr_bbox_rslt
                except Exception as ocr_error:
                    print(f"⚠️ OCR处理出错: {ocr_error}")
                    text, ocr_bbox = [], []
            else:
                print(f"⚠️ OCR已禁用，跳过OCR处理")
                text, ocr_bbox = [], []
            
            # 使用OmniParser处理（与omni.py保持一致）
            labeled_img, label_coordinates, parsed_content_list = get_som_labeled_img(
                image, 
                som_model,
                BOX_TRESHOLD=box_threshold,
                output_coord_in_ratio=True,
                ocr_bbox=ocr_bbox,
                draw_bbox_config=draw_bbox_config,
                caption_model_processor=caption_model_processor,
                ocr_text=text,
                use_local_semantics=True,
                iou_threshold=iou_threshold,
                scale_img=False,
                batch_size=128,
                imgsz=imgsz,
                temperature=temperature,
                repetition_penalty=repetition_penalty
            )
            
            # 格式化解析内容
            parsed_content = '\n'.join([f'icon {i}: {str(v)}' for i, v in enumerate(parsed_content_list)])
            
            return jsonify({
                'success': True,
                'image': labeled_img,  # 已经是base64格式
                'parsed_content': parsed_content,
                'parsed_content_list': parsed_content_list,  # 添加列表格式
                'label_coordinates': label_coordinates,
                'total_icons': len(parsed_content_list)
            })
            
        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/yolo/models', methods=['GET'])
def list_yolo_models():
    """列出可用的YOLO模型"""
    try:
        models = []
        
        # 默认YOLO模型
        models.append({
            'name': 'icon_detect (默认)',
            'path': 'weights/icon_detect/model.pt',
            'type': 'yolo'
        })
        
        # 扫描训练的YOLO模型
        # 这里可以添加扫描逻辑
        
        return jsonify({"success": True, "models": models})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== 静态文件服务 ====================

@app.route('/')
def index():
    """主页"""
    return send_from_directory('frontend', 'index.html')


@app.route('/<path:path>')
def static_files(path):
    """静态文件"""
    return send_from_directory('frontend', path)


@app.route('/config')
def get_config():
    """获取前端配置"""
    return jsonify({
        "success": True,
        "config": {
            "annotation": config['annotation'],
            "ui": config['ui'],
            "export": config['export']
        }
    })


@app.route('/api/projects/<project_id>/categories', methods=['GET'])
def get_project_categories(project_id):
    """获取项目中的所有类别"""
    try:
        import os
        import json
        
        project_dir = os.path.join(config['data']['projects_dir'], project_id)
        annotations_dir = os.path.join(project_dir, 'annotations')
        
        if not os.path.exists(annotations_dir):
            return jsonify({
                'success': False,
                'error': '项目不存在'
            })
        
        # 收集所有类别
        categories = set()
        for filename in os.listdir(annotations_dir):
            if filename.endswith('.json') and not filename.startswith('backup_'):
                filepath = os.path.join(annotations_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for ann in data.get('annotations', []):
                            category = ann.get('category', '')
                            if category:
                                categories.add(category)
                except Exception as e:
                    print(f"读取标注文件失败 {filename}: {e}")
                    continue
        
        return jsonify({
            'success': True,
            'categories': sorted(list(categories))
        })
        
    except Exception as e:
        import traceback
        print(f"获取类别失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/projects/<project_id>/negative_samples', methods=['POST'])
def add_negative_samples(project_id):
    """自动添加负样本"""
    try:
        import os
        import sys
        
        # 添加项目根目录到路径
        project_root = os.path.dirname(os.path.abspath(__file__))
        if project_root not in sys.path:
            sys.path.append(project_root)
        
        data = request.json
        category_name = data.get('category', '通用图标')
        confidence_threshold = float(data.get('confidence_threshold', 0.3))
        
        # 导入负样本添加函数
        from add_negative_samples import auto_add_negative_samples
        
        # 执行自动添加
        success, message, stats = auto_add_negative_samples(
            project_id=project_id,
            category_name=category_name,
            confidence_threshold=confidence_threshold
        )
        
        return jsonify({
            'success': success,
            'message': message,
            'stats': stats
        })
        
    except Exception as e:
        import traceback
        print(f"添加负样本失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        })


if __name__ == '__main__':
    host = config['server']['host']
    port = config['server']['port']
    debug = config['server']['debug']
    
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║        🤖 朱笔 Zhubi · 本地图像标注与微调平台                ║
║                                                           ║
║        服务器地址: http://{host}:{port}                    
║                                                           ║
║        功能特性:                                           ║
║        ✅ 图形化标注界面                                    ║
║        ✅ 多格式导出 (COCO/YOLO/Florence-2)                ║
║        ✅ Florence-2增量训练                               ║
║        ✅ 项目管理和数据统计                                ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    app.run(host=host, port=port, debug=debug)
