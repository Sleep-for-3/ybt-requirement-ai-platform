from dataclasses import dataclass,field
@dataclass
class KnowledgeUnitDraft:
    unit_type:str;title:str;content:str;source_sheet_name:str|None=None;source_page_no:int|None=None;source_heading:str|None=None;source_cell_range:str|None=None;target_table_code:str|None=None;target_field_code:str|None=None;target_field_name:str|None=None;source_table_name:str|None=None;source_field_name:str|None=None;tags:list[str]=field(default_factory=list);metadata:dict=field(default_factory=dict)
