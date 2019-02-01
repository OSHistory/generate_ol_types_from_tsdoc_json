import json 
import os 
import re 
import yaml 

class TSDefinitionWriter():

    def __init__(self, json_path):
        with open(json_path) as fh:
            self.content = json.load(fh)

        # A list of all referenced ids for the currently parsed 
        # module, will be processed on writing the module to .d.ts-file
        self.module_imports = []
        # The default export of the module 
        # assumes name with same name (the class)
        self.default_export = None
        # A list of all generic classes of openlayers, information 
        # is unfortunately dropped during export to json
        self.generic_classes = ['Collection', 'FeatureCollection']
        self.id_type_dict = {}
        self.fixes = self._parse_fixes()
        print(self.fixes["code-replacement"])
        # TODO: debug -> remove
        self.kind_dict = {}
        self._generate_id_type_dict(self.content, self.id_type_dict, None)
        print(self.kind_dict)
        self._parse_modules()

    def _parse_fixes(self):
        with open("fixes.yaml") as fh:
            fixes = yaml.load(fh)
        return fixes

    """
    Maps typedoc-ids to import paths and json-representation
    """
    def _generate_id_type_dict(self, child_node, id_dict, import_path):
        # TODO: debug
        if child_node["kind"] not in self.kind_dict:
            self.kind_dict[child_node["kind"]] = 0
        else:
            self.kind_dict[child_node["kind"]] += 1

        # Overwrite if own original name (else use parent's value)
        if "originalName" in child_node:
            import_path = self._js_to_ts_def_path(child_node["originalName"])
            
        id_dict[child_node["id"]] = {
            "nodeObj": child_node,
            "importPath": import_path
        }

        if "children" in child_node:
            for child in child_node["children"]:
                self._generate_id_type_dict(child, id_dict, import_path)

    def _parse_modules(self):
        for module in self.content["children"]:
            self.module_imports = []
            self.default_export = None
            self._parse_module(module)

    def _parse_module(self, module):
        print(module["originalName"])
        path = module["originalName"].rpartition("/src/")[2]
        def_path = os.path.join("@types", path).replace(".js", ".d.ts")
        module_string = ""
        module_name = module["name"].strip("\"")

        if module_name in self.fixes["code-injection"]:
            module_string += self.fixes["code-injection"][module_name] + "\n"
            print("ADDING")
            print(module_string)
        if "children" in module:
            for member in module["children"]:
                curr_string = self._resolve_node(member, path)
                if curr_string is not None:
                    module_string += curr_string
        path = self._js_to_ts_def_path(module["originalName"])
        dir_name = os.path.dirname(path)
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
        module_string = self.resolve_imports(self.module_imports, def_path, module) + module_string

        # TODO: fix absolute paths or compile in first step
        with open(module["originalName"].replace("magellan", "americo").replace("srcCode", "")) as fh:
            js_content = fh.read()

        default_export = self._get_default_export(js_content)
        if default_export is not None:
            print("DEFAULT EXPORT")
            print(default_export)
            module_string += "\n\nexport default {default_export};".format(default_export=default_export)

        print("RUNNING REPLACEMENTS")
        print(module_name)
        if module_name in self.fixes["code-replacement"]:
            print("MODULE HITS")
            replace_list = self.fixes["code-replacement"][module_name]
            for idx in range(0, len(replace_list)):
                if idx % 2 == 0:
                    module_string = module_string.replace(replace_list[idx], replace_list[idx+1])

        with open(path, "w+") as fh:
            fh.write(module_string)

    """
    Information about default export is not provided by json, get 
    it directly from the .js source 
    """
    def _get_default_export(self, js_content):
        export_line = re.search("^export default .*?;", js_content, re.MULTILINE)
        if export_line is not None:
            print("NOT NONE LINE")
            print(export_line.group())
            default_export = export_line.group().strip(";").strip().rpartition(" ")[2]
            return default_export

    def resolve_imports(self, import_ids, def_path, module):
        import_str = ""
        _id = module["id"]
        import_path_dict = {}
        for _id in import_ids:
            name = self.id_type_dict[_id]["nodeObj"]["name"]
            curr_path = self.id_type_dict[_id]["importPath"]
            if curr_path not in import_path_dict:
                import_path_dict[curr_path] = []
            if name not in import_path_dict[curr_path]:
                import_path_dict[curr_path].append(name)
        for import_path in import_path_dict.keys():
            if import_path != def_path:
                relative_dir_path = os.path.relpath(
                    os.path.dirname(import_path), 
                    os.path.dirname(def_path)
                )
                relative_path = os.path.join(
                    "./",
                    relative_dir_path, 
                    os.path.basename(import_path).replace(".d.ts", "")
                )
                import_str += 'import {{ {names} }} from "{import_path}";\n'.format(
                    names=", ".join(import_path_dict[import_path]),
                    import_path=relative_path
                )
        module_name = module["name"].strip("\"")
        if module_name in self.fixes["import-hooks"]:
            import_str += self.fixes["import-hooks"][module_name] + "\n"

        return import_str

    def _merge_imports(self, imports, add_imports):
        for _import in add_imports:
            if _import not in imports:
                imports[_import] = add_imports[_import]
            else:
                for sub_import in add_imports[_import]:
                    if sub_import not in imports[_import]:
                        imports[_import].append(sub_import)
        return imports

    def _resolve_node(self, node, path):

        if node["name"] == os.path.basename(path).rpartition(".")[0].strip():
            self.default_export = node["name"]
        if node["kind"] == 128:
            return self._resolve_class_node(node) # "CLASS DECLARATION"
        elif node["kind"] == 64:
            if self._is_exported(node):
                return self._resolve_function_node(node)
        else: 
            pass
            # print("UNIMPLEMENTED KIND!")
            # print(node["kind"])

        return None

    def _is_exported(self, node):
        if "isExported" in node["flags"]:
            return node["flags"]["isExported"]
        return False

    def _resolve_function_node(self, node):
        fun_name = node["name"]
        if "parameters" not in node["signatures"][0]:
            param_str = ""
        else:
            param_str = self._stich_params(node["signatures"][0]["parameters"])
        return_str = self._resolve_type(node["signatures"][0]["type"])

        return "export declare function {name}({param_str}): {return_str};\n\n".format(
            name=fun_name,
            param_str=param_str,
            return_str=return_str
        )

    def _resolve_class_node(self, node):
        class_string = "\n\n"
        if self._is_exported(node):
            class_string += "export "
        class_string += "declare class " + node["name"]
        if node["name"] in self.generic_classes:
            class_string += "<T>"
        # check if extends a base class
        if "extendedTypes" in node:
            if "id" in node["extendedTypes"][0]:
                extension_id = node["extendedTypes"][0]["id"]
                if extension_id not in self.module_imports:
                    self.module_imports.append(extension_id)
            class_string += " extends " + node["extendedTypes"][0]["name"]
            if node["extendedTypes"][0]["name"] in self.generic_classes:
                class_string += "<T>"
        class_string += " {\n"
        
        # iterate all class children (constructor and methods)
        for child in node["children"]:
            if child["kindString"] == "Constructor":
                constructor_string = self._resolve_constructor(child)
                class_string += constructor_string
            elif child["kindString"] == "Method":
                if "isExported" in child["flags"]:
                    if child["flags"]["isExported"]:
                        method_string = self._resolve_method(child)
                        class_string += method_string
            else:
                print("DIFFERENT class child!")
                print(child["kindString"])
    
        class_string += "}\n\n"
        return class_string

    def _resolve_method(self, class_child):
        if "parameters" not in class_child["signatures"][0]:
            param_str = ""
        else:
            param_str = self._stich_params(class_child["signatures"][0]["parameters"])

        fun_name = class_child["signatures"][0]["name"]
        return_str = self._resolve_type(class_child["signatures"][0]["type"])

        return "  {fun_name}({params}): {return_str};\n\n".format(
                fun_name=fun_name,
                params=param_str,
                return_str=return_str
            )

    # TODO: resolve imports resulting from types
    def _resolve_type(self, type_obj):
        if type_obj["type"] == "union":
            type_str_list = []
            for _type in type_obj["types"]:
                type_str_list.append(self._resolve_type(_type))
            return "|".join(type_str_list)
        elif type_obj["type"] == "intrinsic":
            return type_obj["name"]
        elif type_obj["type"] == "reference":
            name = type_obj["name"]
            if "id" in type_obj:
                self.module_imports.append(type_obj["id"])
            # TODO: handle typeArguments for non generic classes
            if "typeArguments" in type_obj and name in self.generic_classes:
                # TODO: safe to assume only one argument?
                name += "<" + self._resolve_type(type_obj["typeArguments"][0]) + ">"                    
            else: 
                print("WARNING! No ID!")
                print(type_obj)
            return name
        elif type_obj["type"] == "array":
            return self._resolve_type(type_obj["elementType"]) + "[]"
        else:
            print("DIFFERENT TYPE RETURN!")
            print(type_obj)
            return "any"
        
    def _resolve_constructor(self, class_child):
        if "parameters" not in class_child["signatures"][0]:
            param_str = ""
        else:
            param_str = self._stich_params(class_child["signatures"][0]["parameters"])
        return "  constructor({params});\n\n".format(params=param_str)

     
    def _stich_params(self, params):
        param_str_list = []
        for param in params:
            optional = param["name"].startswith("opt_")
            name = param["name"]
            if optional:
                name += "?"
            type_str = self._resolve_type(param["type"])
            param_str_list.append("{name}: {_type}".format(name=name, _type=type_str))
        return ", ".join(param_str_list)

    # def check_class_extension(self, constructor_signature):
    #     if "overwrite" in constructor_signature:


    def _js_to_ts_def_path(self, js_path):
        path = js_path.rpartition("/src/")[2]
        def_path = os.path.join("@types", path).replace(".js", ".d.ts")
        return def_path

tsdw = TSDefinitionWriter("oldoc.json")
