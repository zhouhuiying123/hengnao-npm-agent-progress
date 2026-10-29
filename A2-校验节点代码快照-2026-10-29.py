# coding=utf-8
from runtime import Args
import uuid
import json
import os
import re

def handler(args: Args) -> dict:

    # 1. 获取 FlashLLM 输出的 JSON 字符串
    raw = args.input.result

    # 2. JSON 解析
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw

        if not isinstance(data, dict):
            raise ValueError("JSON 顶层必须是对象")

    except (json.JSONDecodeError, TypeError, ValueError):
        return {
            "valid": False,
            "status": "input_error",
            "message": "JSON 解析失败"
        }

    # 3. 提取字段
    package = data.get("package")
    version = data.get("version")
    metadata = data.get("metadata")

    # 4. 校验必填项
    if not isinstance(package, str) or not package.strip():
        return {
            "valid": False,
            "status": "input_error",
            "message": "包名不能为空"
        }

    if not isinstance(version, str) or not version.strip():
        return {
            "valid": False,
            "status": "input_error",
            "message": "版本不能为空"
        }

    package = package.strip()
    version = version.strip()

    # 5. 校验 npm 包名格式（基础校验）
    name_pattern = r"(?:@[a-z0-9._~-]+/)?[a-z0-9._~-]+"

    if not re.fullmatch(name_pattern, package):
        return {
            "valid": False,
            "status": "input_error",
            "message": "npm 包名格式不合法"
        }

    # 6. 校验精确版本号（基础 SemVer 校验）
    num = r"(?:0|[1-9][0-9]*)"

    version_pattern = (
        rf"{num}\.{num}\.{num}"
        rf"(?:-[0-9A-Za-z.-]+)?"
        rf"(?:\+[0-9A-Za-z.-]+)?"
    )

    if not re.fullmatch(version_pattern, version):
        return {
            "valid": False,
            "status": "input_error",
            "message": "版本号必须为精确版本，例如 1.2.3"
        }

    # 7. 解析 metadata
    if metadata is None or metadata == "":
        metadata = None

    elif isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            return {
                "valid": False,
                "status": "input_error",
                "message": "metadata 不是合法 JSON"
            }

    if metadata is not None:
        if not isinstance(metadata, dict):
            return {
                "valid": False,
                "status": "input_error",
                "message": "metadata 必须是 JSON 对象"
            }

        # 8. 检查元数据与请求是否一致
        if "name" in metadata and metadata["name"] != package:
            return {
                "valid": False,
                "status": "conflict",
                "message": "元数据中的包名与请求不一致"
            }

        if "version" in metadata and metadata["version"] != version:
            return {
                "valid": False,
                "status": "conflict",
                "message": "元数据中的版本与请求不一致"
            }

    # 9. 校验通过
    return {
        "valid": True,
        "status": "completed",
        "message": "输入校验通过",
        "package": package,
        "version": version,
        "metadata": json.dumps(metadata, ensure_ascii=False)
                    if metadata is not None else ""
    }
    
    # 使用"args.input.变量名"可以获取代码节点输入参数的具体参数值，示例如下：
    # a = args.input.a
    # b = args.input.b

    # 当输入参数为文件，需要在代码节点中获取该文件的内容，示例如下：
    # fb = FileBucket() # 根据节点提供的SDK方法，实例化一个FileBucket对象
    # filename = args.input.filename # 获取需要读取的文件名
    # byte_stream = fb.get(filename) # 通过get方法获取到文件流，后续可根据实际需要对文件流进行处理

    # 当代码节点中生成一个文件需要保存输出，示例如下：
    # fb = FileBucket() # 根据节点提供的SDK方法，实例化一个FileBucket对象
    # filename = fb.save('results.xlsx',binary_data) # 通过save方法将文件流写入到对应的文件中并保存

    # 调用大模型接口-方法一（推荐使用）
    # from openai import OpenAI
    # client = OpenAI()
    # response1 = client.chat.completions.create(
    #     model = "HengNao-v4",
    #     temperature = 0.7,
    #     max_tokens = 1024,
    #     top_p = 1, 
    #     extra_body = {
    #         "top_k": -1  
    #     },
    #     messages = [
    #        { "role": "user", "content": "你好" }
    #     ]
    # )
    # print(response1.choices[0].message.content)

    # 调用大模型接口-方法二
    # from langchain_openai import ChatOpenAI
    # from langchain_core.messages import HumanMessage

    # llm = ChatOpenAI(
    #     model="HengNao-v4",
    # )
    # response2 = llm.invoke([
    #     HumanMessage(content="你好")
    # ])

    # 在代码节点运行过程中临时写入文件内容
    # with open('1.txt','w') as f:
    #     f.write("xxxxxxxxxxxx")

    # 在代码节点运行过程中临时读取文件内容
    # with open('1.txt','r') as f:
    #     result = f.readline()

    # return {
    #     'response1': response1,
    #     'response2': response2,
    # }
