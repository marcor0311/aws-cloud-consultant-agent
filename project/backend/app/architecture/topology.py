"""Typed architecture topology and deterministic diagram projections."""

import re
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

AWSDAC_VERSION = "0.24"
AWSDAC_DEFINITION_URL = (
    "https://raw.githubusercontent.com/awslabs/diagram-as-code/"
    f"v{AWSDAC_VERSION}/definitions/definition-for-aws-icons-light.yaml"
)
SUPPORTED_AWS_RESOURCE_TYPES = frozenset(
    {
        "AWS::ApiGateway::RestApi",
        "AWS::CloudFront::Distribution",
        "AWS::Cognito::UserPool",
        "AWS::DynamoDB::Table",
        "AWS::EC2::Instance",
        "AWS::EC2::InternetGateway",
        "AWS::EC2::Subnet",
        "AWS::EC2::VPC",
        "AWS::KMS",
        "AWS::Lambda::Function",
        "AWS::S3::Bucket",
        "AWS::SNS::Topic",
        "AWS::SQS::Queue",
        "AWS::WAFv2::WebACL",
    }
)


class TopologyContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TopologyNode(TopologyContract):
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    aws_resource_type: str = Field(pattern=r"^AWS::[A-Za-z0-9]+(?:::[A-Za-z0-9]+)?$")
    title: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def resource_type_is_supported(self):
        if self.aws_resource_type not in SUPPORTED_AWS_RESOURCE_TYPES:
            raise ValueError(
                "Tipo AWS no verificado en la definición awsdac fijada: "
                f"{self.aws_resource_type}."
            )
        return self


class TopologyRelation(TopologyContract):
    relation_id: str = Field(pattern=r"^REL-[0-9]{3}$")
    source: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    target: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    relation_type: Literal["functional", "deployment_dependency"]
    label: str = Field(min_length=1, max_length=120)


class ArchitectureTopology(TopologyContract):
    nodes: list[TopologyNode] = Field(min_length=1, max_length=100)
    relations: list[TopologyRelation] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def references_are_valid(self):
        node_ids = [node.resource_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Los nodos de topología no pueden repetirse.")
        relation_ids = [relation.relation_id for relation in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("Las relaciones de topología no pueden repetirse.")
        known = set(node_ids)
        for relation in self.relations:
            if relation.source == relation.target:
                raise ValueError(
                    "Una relación no puede conectar un recurso consigo mismo."
                )
            if relation.source not in known or relation.target not in known:
                raise ValueError("Toda relación debe referenciar nodos existentes.")
        return self

    def mermaid(self) -> str:
        lines = ["flowchart LR"]
        for node in sorted(self.nodes, key=lambda item: item.resource_id):
            identifier = re.sub(r"[^A-Za-z0-9_]", "_", node.resource_id)
            title = node.title.replace('"', "'")
            lines.append(f'  {identifier}["{title}"]')
        identifiers = {
            node.resource_id: re.sub(r"[^A-Za-z0-9_]", "_", node.resource_id)
            for node in self.nodes
        }
        for relation in sorted(self.relations, key=lambda item: item.relation_id):
            arrow = (
                "-.->" if relation.relation_type == "deployment_dependency" else "-->"
            )
            label = relation.label.replace('"', "'")
            lines.append(
                f'  {identifiers[relation.source]} {arrow}|"{label}"| '
                f"{identifiers[relation.target]}"
            )
        return "\n".join(lines) + "\n"

    def awsdac_document(self) -> dict:
        nodes = sorted(self.nodes, key=lambda item: item.resource_id)
        resources = {
            "Canvas": {
                "Type": "AWS::Diagram::Canvas",
                "Direction": "horizontal",
                "Children": [node.resource_id for node in nodes],
            }
        }
        for node in nodes:
            resources[node.resource_id] = {
                "Type": node.aws_resource_type,
                "Title": node.title,
            }
        links = []
        for relation in sorted(self.relations, key=lambda item: item.relation_id):
            link = {
                "Source": relation.source,
                "Target": relation.target,
                "TargetArrowHead": {"Type": "Open"},
                "Labels": {"AutoRight": {"Title": relation.label}},
            }
            if relation.relation_type == "deployment_dependency":
                link["LineStyle"] = "dashed"
            links.append(link)
        return {
            "Diagram": {
                "DefinitionFiles": [{"Type": "URL", "Url": AWSDAC_DEFINITION_URL}],
                "Resources": resources,
                "Links": links,
            }
        }

    def awsdac_yaml(self) -> str:
        return yaml.safe_dump(
            self.awsdac_document(),
            sort_keys=False,
            allow_unicode=True,
        )
